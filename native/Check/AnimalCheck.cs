using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Threading.Tasks;
using AnimaNative.Figures;
using AnimaNative.World;
using Godot;

namespace AnimaNative.Check;

/// <summary>
/// <c>--check animals</c> (part of every <c>--check</c>, Task 34): animals and clip-less rigs like the browser (figures.ts
/// <c>buildModel</c>'s FBX branch, the Figure constructor's actions and leg chains, <c>Figure.update</c>'s static branch)
/// on the hand-made world <c>fixtures/animals/</c> (README "Animals world"; the FBX files are written by
/// <c>tools/animal_fbx.py</c> with the server's quadruped exporter settings). Three animals, each 0.5 m tall in the file
/// and 50 cm in the world map (scale 1):
///
///   N1 Rex (<c>generic</c>, three takes, <c>model.clips</c> walk loop / sit once): an FBX body, actions [idle, sit, walk],
///      loop flags idle (no flag) and walk loop, sit once; the browser material (roughness 0.85, metallic 0, Lambert, no
///      received shadows, clamped); bind anchoring (0, 0, 0.05), height 0.5;
///   N2 the UV texel probe: Godot's import turns v into 1 − v; with the flipped texture every part of the mesh samples the
///      texel three samples with <c>flipY = false</c> — body (96, 48, 200), legs (224, 112, 200), tail (32, 208, 200);
///   N3 the takes play on the rig: walk at 0.3 s turns every hip 8° from its rest (linear keys 0 → 20° over 0.125 s,
///      back through 0 at 0.25 s); sit, a one-shot, holds its last frame (back hips 60°, front hips at rest);
///   N4 Spot (<c>generic</c>, no takes) and Dot (rig <c>none</c> on the file WITH takes) are static: no action, four leg
///      chains (the hips; feet the paws), world axis X stored in the rolled spine's frame (not X there), walk phases
///      BL 0 / FL π/2 / BR π / FR 3π/2 and the
///      trot BL = FR = 0, BR = FL = π;
///   N5 Spot's gait from phase 0: one 0.1 s walking frame swings FL by 0.45·cos 0.7 and bobs |sin 0.7|·0.01 m — the paws
///      land at the derived points; standing 0.5 s from idle phase 0 rests the legs, bobs 0.012·sin 0.8 and breathes
///      1 + 0.006·sin 0.4; a running frame advances 1.1 rad (the diagonals swing ±0.45·sin 1.1);
///   N6 through the NPC walk: a 2 m goal walks (3.4 m/s, phase +0.7 in 0.1 s), a 10 m goal runs (×1.8, phase +1.1).
/// </summary>
public static class AnimalCheck
{
    private const double Tol = 1e-4;
    private const double DegTol = 0.01;
    private const int TexW = 4, TexH = 8;
    private static double Rad(double deg) => deg * Math.PI / 180;

    public static async Task<string> RunAsync(Node3D host, string fixtures)
    {
        var dir = Path.Combine(fixtures, "animals");
        var source = new FixtureSource(dir, fixtures);
        var world = new Node3D { Name = "AnimalWorld" };
        host.AddChild(world);
        try
        {
            Expect("N0 IsFbx by format", FigureManager.IsFbx("fbx", "/m/file?v=1"), "format fbx");
            Expect("N0 IsFbx by URL (.FBX?…)", FigureManager.IsFbx("glb", "/m/Model.FBX?v=1"), "url");
            Expect("N0 a .glb under /fbx/ is glTF", !FigureManager.IsFbx("glb", "/fbx/model.glb"), "url");
            using var hf = JsonDocument.Parse(File.ReadAllBytes(Path.Combine(fixtures, "heightfield.json")));
            var height = new WorldHeight(HeightfieldOverview.Parse(hf.RootElement));
            var mgr = new FigureManager(source, height, line => GD.Print("[check-animals] " + line), strict: true) { AutoTick = false };
            world.AddChild(mgr);
            await mgr.InitAsync();
            await Apply(mgr, dir, "worldmap.json");
            var f = mgr.Figures;
            Figure rex = f["Rex Takes"], spot = f["Spot Static"], dot = f["Dot None"];

            // ---- N1 Rex: an FBX body with its own takes ----
            Expect("N1 every animal is a model body", new[] { rex, spot, dot }.All(x => x.IsGlb && x.Portrait is null && x.Skeleton is not null),
                   string.Join(", ", new[] { rex, spot, dot }.Select(x => $"{x.CharacterName} model {x.IsGlb} skel {x.Skeleton is not null}")));
            Expect("N1 Rex's actions are its takes", rex.ClipKinds.SequenceEqual(new[] { "idle", "sit", "walk" }), string.Join(",", rex.ClipKinds));
            var player = rex.Player!;
            Expect("N1 idle loops (no flag)", player.GetAnimation("idle").LoopMode == Animation.LoopModeEnum.Linear, "once");
            Expect("N1 walk loops (flag true)", player.GetAnimation("walk").LoopMode == Animation.LoopModeEnum.Linear, "once");
            Expect("N1 sit once (flag false)", player.GetAnimation("sit").LoopMode == Animation.LoopModeEnum.None, "loops");
            NearD("N1 take length 12 frames at 24 fps", player.GetAnimation("walk").Length, 0.5, 1e-6);
            Expect("N1 Rex stands: the idle take", rex.CurrentClip == "idle" && !rex.IsStatic && rex.Legs.Count == 0, $"{rex.CurrentClip} static {rex.IsStatic}");
            NearD("N1 scale 0.50 / 0.50", rex.BaseScale, 1, 1e-4);
            NearD("N1 body height", rex.BodyHeight, 0.5, 1e-4);
            NearV("N1 bind anchoring (box z −0.4 … 0.3)", rex.BindOffset, 0, 0, 0.05, 1e-4);
            var aabb = ModelPlacement.Measure(rex.Body!, Transform3D.Identity);
            NearD("N1 drawn height", aabb.Size.Y, 0.5, 1e-4);
            var (mesh, mat) = Dressed(rex);
            Expect("N1 the browser material", mat.Roughness == 0.85f && mat.Metallic == 0 && !mat.TextureRepeat
                   && mat.DiffuseMode == BaseMaterial3D.DiffuseModeEnum.Lambert && mat.DisableReceiveShadows && mat.AlbedoTexture is ImageTexture,
                   $"roughness {mat.Roughness} metallic {mat.Metallic} repeat {mat.TextureRepeat} diffuse {mat.DiffuseMode}");
            Expect("N1 no metallic material", FigureManager.MetallicMaterials(rex.Body!) == 0, "metallic");
            Expect("N1 each texture downloaded once", source.ByteRequests.Count(u => u.Contains("/model3d/texture", StringComparison.Ordinal)) == 3,
                   string.Join(";", source.ByteRequests));

            // ---- N2 the UV texel probe ----
            var texel = TexelProbe(mesh, mat);

            // ---- N3 the takes on the rig ----
            var skel = rex.Skeleton!;
            rex.Play("walk");
            for (int i = 0; i < 3; i++) rex.UpdateFigure(0.1);
            NearD("N3 walk clock 0.3 s", player.CurrentAnimationPosition, 0.3, 1e-6);
            foreach (var leg in new[] { "FL", "FR", "BL", "BR" })
                NearD($"N3 walk: Hip_{leg} 8° from rest at 0.3 s", FromRestDeg(skel, "Hip_" + leg), 8, DegTol);
            rex.Play("sit");
            for (int i = 0; i < 10; i++) rex.UpdateFigure(0.1);
            Expect("N3 sit ended (one-shot)", !player.IsPlaying() || player.CurrentAnimationPosition >= 0.5 - 1e-6, $"{player.CurrentAnimationPosition}");
            NearD("N3 sit holds its last frame: Hip_BL 60°", FromRestDeg(skel, "Hip_BL"), 60, DegTol);
            NearD("N3 sit holds its last frame: Hip_BR 60°", FromRestDeg(skel, "Hip_BR"), 60, DegTol);
            NearD("N3 sit: Hip_FL at rest", FromRestDeg(skel, "Hip_FL"), 0, DegTol);

            // ---- N4 the static rigs and their leg chains ----
            foreach (var x in new[] { spot, dot })
            {
                Expect($"N4 {x.CharacterName} is static", x.IsStatic && x.Player is null && x.ClipKinds.Count == 0,
                       $"static {x.IsStatic} player {x.Player is not null} kinds {x.ClipKinds.Count}");
                var s = x.Skeleton!;
                var legs = x.Legs.ToDictionary(l => s.GetBoneName(l.Bone).ToString());
                Expect($"N4 {x.CharacterName}: four chains on the hips",
                       legs.Count == 4 && new[] { "FL", "FR", "BL", "BR" }.All(k => legs.TryGetValue("Hip_" + k, out var l) && s.GetBoneName(l.Foot) == "Paw_" + k),
                       string.Join(",", x.Legs.Select(l => $"{s.GetBoneName(l.Bone)}→{s.GetBoneName(l.Foot)}")));
                foreach (var (k, walk, run) in new[] { ("BL", 0.0, 0.0), ("FL", Math.PI / 2, Math.PI), ("BR", Math.PI, Math.PI), ("FR", Math.PI * 1.5, 0.0) })
                {
                    var l = legs["Hip_" + k];
                    NearD($"N4 {x.CharacterName} {k} walk phase", l.PhaseWalk, walk, 1e-12);
                    NearD($"N4 {x.CharacterName} {k} trot phase", l.PhaseRun, run, 1e-12);
                    // The spine (the hips' parent) is rolled: the axis is stored in ITS frame, and turned back it is world X.
                    var parentRot = (x.FrameOf(s).Basis * s.GetBoneGlobalPose(s.GetBoneParent(l.Bone)).Basis).GetRotationQuaternion();
                    var worldAxis = parentRot * l.Axis;
                    NearV($"N4 {x.CharacterName} {k} axis = world X", new V3(worldAxis.X, worldAxis.Y, worldAxis.Z), 1, 0, 0, 1e-5);
                    Expect($"N4 {x.CharacterName} {k} the parent frame is not the world's", Math.Abs(l.Axis.X) < 0.5, $"{l.Axis}");
                }
            }

            // ---- N5 Spot's gait, by hand ----
            var ss = spot.Skeleton!;
            spot.WalkPhase = 0;
            spot.Play("walk");
            spot.UpdateFigure(0.1);
            Expect("N5 walking gait", spot.Gait == "walk", spot.Gait ?? "null");
            NearD("N5 phase 7 rad/s", spot.WalkPhase, 0.7, 1e-12);
            double bob = Math.Abs(Math.Sin(0.7)) * 0.02 * 0.5;
            NearD("N5 body bob |sin 0.7|·0.02·0.5", spot.Body!.Position.Y - spot.BindOffset.Y, bob, 1e-6);
            NearD("N5 FL swing 0.45·cos 0.7, deg", FromRestDeg(ss, "Hip_FL"), 0.45 * Math.Cos(0.7) * 180 / Math.PI, DegTol);
            Paw(spot, "FL", -0.1, 0.25, 0.45 * Math.Cos(0.7), bob);
            Paw(spot, "BL", -0.1, -0.15, 0.45 * Math.Sin(0.7), bob);
            Paw(spot, "BR", 0.1, -0.15, -0.45 * Math.Sin(0.7), bob);
            Paw(spot, "FR", 0.1, 0.25, -0.45 * Math.Cos(0.7), bob);
            spot.IdlePhase = 0;
            spot.Play("");
            spot.UpdateFigure(0.5);
            Expect("N5 standing: no gait", spot.Gait is null && spot.CurrentKind == "idle", $"{spot.Gait} {spot.CurrentKind}");
            NearD("N5 idle phase 1.6 rad/s", spot.IdlePhase, 0.8, 1e-12);
            NearD("N5 idle bob 0.012·sin 0.8", spot.Body.Position.Y - spot.BindOffset.Y, 0.012 * Math.Sin(0.8), 1e-6);
            NearD("N5 breath 1 + 0.006·sin 0.4", spot.Body.Scale.Y, 1 + 0.006 * Math.Sin(0.4), 1e-6);
            foreach (var k in new[] { "FL", "FR", "BL", "BR" }) NearD($"N5 standing: Hip_{k} at rest", FromRestDeg(ss, "Hip_" + k), 0, DegTol);
            spot.WalkPhase = 0;
            spot.Play("run");
            spot.UpdateFigure(0.1);
            Expect("N5 running gait", spot.Gait == "run", spot.Gait ?? "null");
            NearD("N5 phase 11 rad/s", spot.WalkPhase, 1.1, 1e-12);
            double runBob = Math.Abs(Math.Sin(1.1)) * 0.02 * 0.5;
            NearD("N5 run bob", spot.Body.Position.Y - spot.BindOffset.Y, runBob, 1e-6);
            NearD("N5 run: body scale back to 1", spot.Body.Scale.Y, 1, 1e-6);
            Paw(spot, "BL", -0.1, -0.15, 0.45 * Math.Sin(1.1), runBob);
            Paw(spot, "FR", 0.1, 0.25, 0.45 * Math.Sin(1.1), runBob);
            Paw(spot, "BR", 0.1, -0.15, -0.45 * Math.Sin(1.1), runBob);
            Paw(spot, "FL", -0.1, 0.25, -0.45 * Math.Sin(1.1), runBob);

            // ---- N6 through the NPC walk: the speed picks the gait ----
            spot.Replay();
            spot.WalkPhase = dot.WalkPhase = 0;
            var spotFrom = spot.Position;
            var dotFrom = dot.Position;
            await Apply(mgr, dir, "worldmap_poll2.json");
            mgr.Tick(0.1);
            Expect("N6 Spot walks (2 m)", spot.Moving && !spot.Running && spot.Gait == "walk", $"moving {spot.Moving} running {spot.Running} gait {spot.Gait}");
            Expect("N6 Dot runs (10 m)", dot.Moving && dot.Running && dot.Gait == "run", $"moving {dot.Moving} running {dot.Running} gait {dot.Gait}");
            NearD("N6 Spot stepped 3.4 m/s · 0.1 s", spot.Position.X - spotFrom.X, 0.34, 1e-4);
            NearD("N6 Dot stepped 3.4 · 1.8 m/s · 0.1 s", dot.Position.X - dotFrom.X, 0.612, 1e-4);
            NearD("N6 Spot's phase +0.7", spot.WalkPhase, 0.7, 1e-12);
            NearD("N6 Dot's phase +1.1", dot.WalkPhase, 1.1, 1e-12);
            NearD("N6 Spot FL swing, deg", FromRestDeg(ss, "Hip_FL"), 0.45 * Math.Cos(0.7) * 180 / Math.PI, DegTol);
            NearD("N6 Dot FL swing, deg", FromRestDeg(dot.Skeleton!, "Hip_FL"), 0.45 * Math.Sin(1.1) * 180 / Math.PI, DegTol);

            mgr.QueueFree();
            return $"animals N1..N6 ok (Rex takes [{string.Join(",", rex.ClipKinds)}] sit once, walk 8° at 0.3 s, sit 60° held; "
                   + $"{texel}; Spot/Dot static, 4 legs each, walk FL {0.45 * Math.Cos(0.7) * 180 / Math.PI:0.000}°, "
                   + $"run ±{0.45 * Math.Sin(1.1) * 180 / Math.PI:0.000}°, idle bob {0.012 * Math.Sin(0.8):0.000000} m)";
        }
        finally
        {
            world.QueueFree();
        }
    }

    private static async Task Apply(FigureManager mgr, string dir, string file)
    {
        using var map = JsonDocument.Parse(File.ReadAllBytes(Path.Combine(dir, file)));
        await mgr.Apply(map.RootElement);
    }

    /// <summary>The body's one mesh and the material the FBX branch dressed it in.</summary>
    private static (MeshInstance3D Mesh, StandardMaterial3D Mat) Dressed(Figure fig)
    {
        var mi = FigureManager.Walk(fig.Body!).OfType<MeshInstance3D>().Single();
        var mat = mi.GetSurfaceOverrideMaterial(0) as StandardMaterial3D
                  ?? throw new InvalidOperationException("animals: the FBX body wears no StandardMaterial3D override");
        return (mi, mat);
    }

    /// <summary>
    /// N2: group the imported vertices by their UV; each group must be one part of the generator's mesh (its mesh-local
    /// extents, the file's centimetres as 0.01 units), carry the file's UV with v turned into 1 − v, and sample — through
    /// the dressed texture — exactly the texel three samples for the file's UV with flipY = false.
    /// </summary>
    private static string TexelProbe(MeshInstance3D mi, StandardMaterial3D mat)
    {
        var arrays = mi.Mesh.SurfaceGetArrays(0);
        var pos = arrays[(int)Mesh.ArrayType.Vertex].AsVector3Array();
        var uv = arrays[(int)Mesh.ArrayType.TexUV].AsVector2Array();
        var img = ((ImageTexture)mat.AlbedoTexture).GetImage()
                  ?? throw new InvalidOperationException("animals: the dressed texture has no image");
        Expect("N2 texture 4 × 8", img.GetWidth() == TexW && img.GetHeight() == TexH, $"{img.GetWidth()} × {img.GetHeight()}");
        // part, the file's UV, the part's Blender extents (x, y, z min/max), the texel three samples
        var parts = new (string Part, Vector2 FileUv, double[] Box, (int R, int G, int B) Want)[]
        {
            ("body", new Vector2(0.375f, 0.1875f), new[] { -0.15, 0.15, -0.3, 0.3, 0.3, 0.5 }, (96, 48, 200)),
            ("legs", new Vector2(0.875f, 0.4375f), new[] { -0.14, 0.14, -0.24, 0.24, 0.0, 0.3 }, (224, 112, 200)),
            ("tail", new Vector2(0.125f, 0.8125f), new[] { -0.02, 0.02, 0.3, 0.4, 0.43, 0.47 }, (32, 208, 200)),
        };
        var groups = Enumerable.Range(0, pos.Length).GroupBy(i => uv[i]).ToList();
        Expect("N2 three UV groups", groups.Count == 3, string.Join(" ", groups.Select(g => g.Key)));
        var lines = new List<string>();
        foreach (var (part, fileUv, box, want) in parts)
        {
            var godotUv = new Vector2(fileUv.X, 1 - fileUv.Y);
            var g = groups.SingleOrDefault(x => x.Key.DistanceTo(godotUv) < 1e-6)
                    ?? throw new InvalidOperationException($"animals: N2 {part}: no vertex with UV {godotUv} (v not turned into 1 − v?)");
            // Mesh-local = the file's (Blender) metres / 100 (the Rig node carries the ×100).
            foreach (int i in g)
            {
                var p = pos[i] * 100;
                Expect($"N2 {part} vertex inside its part", p.X >= box[0] - 1e-4 && p.X <= box[1] + 1e-4 && p.Y >= box[2] - 1e-4
                       && p.Y <= box[3] + 1e-4 && p.Z >= box[4] - 1e-4 && p.Z <= box[5] + 1e-4, $"{p}");
            }
            var c = img.GetPixel((int)Math.Floor(godotUv.X * TexW), (int)Math.Floor(godotUv.Y * TexH));
            var got = ((int)Math.Round(c.R * 255), (int)Math.Round(c.G * 255), (int)Math.Round(c.B * 255));
            Expect($"N2 {part} samples three's texel {want}", got == want, $"{got}");
            // Without the flip the same UV would land on row ⌊v'·8⌋ of the original — another colour.
            int wrongRow = (int)Math.Floor(godotUv.Y * TexH);
            Expect($"N2 {part}: the unflipped texture would be wrong", 16 + 32 * wrongRow != want.G, $"row {wrongRow}");
            lines.Add($"{part} {g.Count()} v → rgb{got}");
        }
        return "texels " + string.Join(", ", lines);
    }

    /// <summary>The angle of a bone's pose rotation from its rest rotation, degrees.</summary>
    private static double FromRestDeg(Skeleton3D skel, string bone)
    {
        int b = skel.FindBone(bone);
        if (b < 0) throw new InvalidOperationException($"animals: no bone {bone}");
        var q = skel.GetBonePoseRotation(b);
        var r = skel.GetBoneRest(b).Basis.GetRotationQuaternion();
        double dot = Math.Min(1, Math.Abs(q.Dot(r)));
        return 2 * Math.Acos(dot) * 180 / Math.PI;
    }

    /// <summary>
    /// A paw in the figure's root frame after a swing <paramref name="swing"/> about X of its hip at (x, 0.3, z) (root
    /// frame, the body anchored): the 0.25 m shank turned, the body raised by <paramref name="bob"/>.
    /// </summary>
    private static void Paw(Figure fig, string leg, double x, double z, double swing, double bob)
    {
        var skel = fig.Skeleton!;
        var p = fig.FrameOf(skel) * skel.GetBoneGlobalPose(skel.FindBone("Paw_" + leg)).Origin;
        double y0 = fig.BindOffset.Y;
        NearV($"N5 {fig.CharacterName} Paw_{leg} after a swing of {swing * 180 / Math.PI:0.###}°", new V3(p.X, p.Y - y0, p.Z),
              x, 0.3 + bob - 0.25 * Math.Cos(swing), z - 0.25 * Math.Sin(swing), Tol);
    }

    private static void Expect(string what, bool ok, string detail)
    {
        if (!ok) throw new InvalidOperationException($"animals: {what} FAILED ({detail})");
    }

    private static void NearD(string what, double got, double want, double tol)
    {
        Expect(what, double.IsFinite(got) && Math.Abs(got - want) <= tol, $"got {got:0.######}, want {want:0.######} ± {tol}");
        GD.Print($"[check-animals] {what}: {got:0.######}");
    }

    private static void NearV(string what, V3 got, double x, double y, double z, double tol)
        => Expect(what, Math.Abs(got.X - x) <= tol && Math.Abs(got.Y - y) <= tol && Math.Abs(got.Z - z) <= tol,
                  $"got ({got.X:0.######}, {got.Y:0.######}, {got.Z:0.######}), want ({x:0.######}, {y:0.######}, {z:0.######}) ± {tol}");
}
