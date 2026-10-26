using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Threading.Tasks;
using AnimaNative.Scene;
using AnimaNative.World;
using Godot;

namespace AnimaNative.Check;

/// <summary>
/// <c>--check props</c> (part of every <c>--check</c>, Task 18): texture slots, mirror panes, prop lights, door props and
/// the room ambience on the hand-written world <c>fixtures/props/</c> (README "Props world"), against numbers derived
/// there by hand:
///
///   P1 slots: the picture lands on the frame's cut clone (white tint, the 2 × 2 poster), the glass preset rides into its
///      cut clone (alpha 0.3, roughness 0.06, metallic 0, two-sided), the wood is untouched, the cached template and a
///      second placement of the same GLB stay bare;
///   P2 mirrors: the pane's plane from the fixture faces (centroid (0.1, 0.3, 0.2), normal ±z), the reflection views of two
///      panes for a camera 2 m in front (eye′, size, off-axis offset, near), Godot's own camera projection agreeing with the
///      lookup rows (UnprojectPosition), the budget rotation over three panes (2 per frame) and the 12 m cap;
///   P3 lights: 8 lamps + 1 world-prop lantern; at night on storey 0 the nearest six are lamps 1, 2, 4, 5, 6, 7 (3 sits in
///      the hidden cellar, the lantern 107 m away); by day lamp 8 takes night-lamp 2's slot (survivors keep theirs); on the
///      cellar storey only lamp 3; the fades, energies and positions; halos under the room/night gate;
///   P4 doors: the leaf hangs in its pivot at (0.05, 0, 0), the leaf keeps its place, shut in the overview, swings for an
///      avatar in range and eases shut again;
///   P5 ambience: the room under the focus (parlour / closet / corridor / cellar / closed) and the eased stage values;
///   P6 a height revision moves the lamps with their lift; P7 the world clock of the map → night 1.
/// </summary>
public static class PropsCheck
{
    private const float Datum = 3.875f;   // tile (0,0): 2·64/64 + 120/64

    public static async Task<string> RunAsync(Node3D host, string fixtures)
    {
        var dir = Path.Combine(fixtures, "props");
        var source = new FixtureSource(dir, fixtures);
        var world = new Node3D { Name = "PropsWorld" };
        host.AddChild(world);
        var builder = new WorldBuilder(source, line => GD.Print("[check-props] " + line), strict: true) { LightSeed = 7 };
        var camera = new Camera3D { Name = "PropsCamera" };
        host.AddChild(camera);
        try
        {
            var stats = await builder.BuildAsync(world, "Lamp House");
            var slot = builder.Slots["loc-room"];
            Near("datum", slot.Group.Position.Y, Datum);
            PlacedModel Rec(string id) => slot.Placements.Single(r => r.Spec.Id == id);

            // ---- P1 slots ----
            await Task.WhenAll(builder.SlotLoads);
            var frame = Rec("frame");
            var fs = frame.Slots!;
            Expect("P1 frame slots", fs.Pictures == 1 && fs.Glass == 1 && fs.Landed == 1 && fs.Failed == 0, $"{fs.Pictures}/{fs.Glass}/{fs.Landed}/{fs.Failed}");
            var fm = FirstMesh(frame.Node!)!;
            // Surfaces: 0 wood, 1 slot_picture_1, 2 slot_glass_1 (make_glbs.py) — all cut by the frame's keep-all plane.
            var pic = fm.GetSurfaceOverrideMaterial(1) as ShaderMaterial;
            var tex = pic?.GetShaderParameter("texture_albedo").As<Texture2D>();
            Expect("P1 picture on the cut clone", pic is not null && tex is not null && tex.GetWidth() == 2 && tex.GetHeight() == 2
                   && pic.GetShaderParameter("albedo").AsColor() == new Color(1, 1, 1, 1)
                   && pic.GetShaderParameter("albedo_texture_size").AsVector2I() == new Vector2I(2, 2), $"{pic} {tex}");
            var glass = fm.GetSurfaceOverrideMaterial(2) as ShaderMaterial;
            var ga = glass?.GetShaderParameter("albedo").AsColor() ?? default;
            Expect("P1 glass on the cut clone", glass is not null && Math.Abs(ga.A - 0.3f) < 1e-6
                   && Math.Abs(glass.GetShaderParameter("roughness").AsSingle() - 0.06f) < 1e-6
                   && glass.GetShaderParameter("metallic").AsSingle() == 0f
                   && glass.Shader.Code.Contains("blend_mix") && glass.Shader.Code.Contains("cull_disabled")
                   && glass.Shader.Code.Contains("cut_plane"), $"{ga}");
            var wood = fm.GetSurfaceOverrideMaterial(0) as ShaderMaterial;
            Expect("P1 wood untouched (its cut clone of the template)", wood is not null
                   && wood.GetShaderParameter("albedo").AsColor().A == 1f
                   && wood.GetShaderParameter("texture_albedo").VariantType == Variant.Type.Nil, "");
            Expect("P1 the cached template stays bare", fm.Mesh.SurfaceGetMaterial(1) is StandardMaterial3D t1 && t1.AlbedoTexture is null
                   && fm.Mesh.SurfaceGetMaterial(2) is StandardMaterial3D t2 && t2.Transparency == BaseMaterial3D.TransparencyEnum.Disabled, "");
            var other = FirstMesh(Rec("frame-2").Node!)!;
            Expect("P1 a second placement of the GLB is not filled", Rec("frame-2").Slots is null
                   && other.GetSurfaceOverrideMaterial(1) is null && other.GetSurfaceOverrideMaterial(2) is null, "");

            // ---- P2 mirrors ----
            var mirrors = builder.Mirrors!;
            Eq("P2 panes", mirrors.Panes.Count, 3);
            var paneA = mirrors.Panes.Single(p => IsUnder(p.Mesh, Rec("mirror-a").Node!));
            var paneB = mirrors.Panes.Single(p => IsUnder(p.Mesh, Rec("mirror-b").Node!));
            Expect("P2 plane from the pane's faces", Close(paneA.Plane.Point, 0.1, 0.3, 0.2, 1e-6) && Math.Abs(Math.Abs(paneA.Plane.Normal.Z) - 1) < 1e-9,
                   $"{paneA.Plane}");
            Expect("P2 the pane wears the mirror material", paneA.Mesh.GetSurfaceOverrideMaterial(paneA.Surface) == paneA.Material
                   && ShaderSafety.Lines.Contains("shader mirror: compiled (6 uniforms)"), string.Join(" | ", ShaderSafety.Lines.Where(l => l.Contains("mirror"))));
            // A closed location's interior is hidden, so its panes draw nothing and ask for nothing (three's hooks fire only
            // for drawn meshes): no pass before the location is opened.
            camera.GlobalPosition = new Vector3(64, 4.5375f, 128.05f);
            Eq("P2 closed: no pass", mirrors.Tick(camera), 0);
            Expect("P2 open", builder.SetOpen("loc-room", true), "");
            for (int i = 0; i < 60; i++) builder.TickView(1.0 / 60, camera.GlobalPosition);
            Expect("P2 interior shown", Rec("mirror-a").Node!.IsVisibleInTree(), $"fade {slot.Fade.Fade}");
            var sets = new List<string>();
            for (int f = 0; f < 3; f++)
            {
                var before = mirrors.Panes.Select(p => p.Passes).ToArray();
                int grants = mirrors.Tick(camera);
                sets.Add(grants + ":" + string.Join("", Enumerable.Range(0, 3).Where(i => mirrors.Panes[i].Passes > before[i])));
            }
            Expect("P2 two passes a frame, in turns", string.Join(" ", sets) == "2:01 2:02 2:12", string.Join(" ", sets));
            // Pane A: centre (64, 4.5375, 124.05), eye 4 m in front → eye′ (64, 4.5375, 120.05), window 0.5 × 1 → size 1, centred.
            var va = paneA.LastView!.Value;
            Expect("P2 view A", Close(va.Eye, 64, 4.5375, 120.05, 1e-4) && Math.Abs(va.Size - 1) < 1e-4 && Math.Abs(va.OffsetX) < 1e-4
                   && Math.Abs(va.OffsetY) < 1e-4 && Math.Abs(va.Near - 4) < 1e-4, $"{va.Eye} {va.Size} {va.OffsetX} {va.OffsetY} {va.Near}");
            // Pane B: centre (62, 4.475, 124.05); x_c = −(x − 64) ∈ [1.75, 2.25], y_c ∈ [−0.5625, 0.4375] → offset (2, −0.0625).
            var vb = paneB.LastView!.Value;
            Expect("P2 view B off-axis", Math.Abs(vb.Size - 1) < 1e-4 && Math.Abs(vb.OffsetX - 2) < 1e-4 && Math.Abs(vb.OffsetY + 0.0625) < 1e-4,
                   $"{vb.Size} {vb.OffsetX} {vb.OffsetY}");
            var cb = paneB.Camera;
            Expect("P2 camera B set", Math.Abs(cb.Size - 1) < 1e-4 && cb.FrustumOffset.DistanceTo(new Vector2(2, -0.0625f)) < 1e-4
                   && Math.Abs(cb.Near - 4) < 1e-4 && cb.GlobalPosition.DistanceTo(new Vector3(64, 4.5375f, 120.05f)) < 1e-3, $"{cb.Size} {cb.FrustumOffset} {cb.Near}");
            // Godot's projection of the off-axis frustum vs the lookup rows: the pane centre at the image middle, the pane's
            // top-left (61.75, 4.975) at u = (2.25 − 1.5)/1 = 0.75, v = 0 → (384, 0) of 512.
            var c0 = cb.UnprojectPosition(new Vector3(62, 4.475f, 124.05f));
            var c1 = cb.UnprojectPosition(new Vector3(61.75f, 4.975f, 124.05f));
            var t0 = MirrorMath.TexCoord(vb, new Overview.Vec3(62, 4.475, 124.05));
            var tc1 = MirrorMath.TexCoord(vb, new Overview.Vec3(61.75, 4.975, 124.05));
            Expect("P2 Godot camera = lookup rows", c0.DistanceTo(new Vector2(256, 256)) < 0.5f && c1.DistanceTo(new Vector2(384, 0)) < 0.5f
                   && Math.Abs(t0.U - 0.5) < 1e-4 && Math.Abs(t0.V - 0.5) < 1e-4 && Math.Abs(tc1.U - 0.75) < 1e-4 && Math.Abs(tc1.V) < 1e-4,
                   $"{c0} {c1} ({t0.U},{t0.V}) ({tc1.U},{tc1.V})");
            Expect("P2 rows on the drawn material", ((ShaderMaterial)paneA.Mesh.GetSurfaceOverrideMaterial(paneA.Surface)).GetShaderParameter("tex_w").AsVector4()
                       .DistanceTo(new Vector4((float)va.TexW[0], (float)va.TexW[1], (float)va.TexW[2], (float)va.TexW[3])) < 1e-4, "");
            camera.GlobalPosition = new Vector3(64, 4.5375f, 160);
            Eq("P2 beyond 12 m nothing refreshes", mirrors.Tick(camera), 0);

            // ---- P3 lights ----
            var pool = builder.PropLights!;
            Eq("P3 sources", pool.State.Count, 9);
            var focus = new Vector3(64, 5.875f, 120);
            Expect("P3 lamp 1 position", Close(pool.State.PositionOf(Rec("lamp-1").LightId!)!.Value, 65, 5.90625, 120, 1e-5), "");
            Expect("P3 lamp 3 (cellar, no lift)", Close(pool.State.PositionOf(Rec("lamp-3").LightId!)!.Value, 67, 2.875, 120, 1e-5), "");
            builder.TickProps(0.2, null, focus, 1);
            Expect("P3 night, storey 0", pool.State.Selected.SequenceEqual(new[] { "1", "2", "4", "5", "6", "7" }), string.Join(",", pool.State.Selected));
            Expect("P3 fresh slots at gain 0", pool.Lamps.All(l => l.LightEnergy == 0f), "");
            // Task 26b: a lamp at energy 0 adds nothing, so it is not even clustered (hidden until it has light).
            Expect("P3 dark slots are hidden", pool.Lamps.All(l => !l.Visible), "");
            builder.TickProps(0.2, null, focus, 1);
            Expect("P3 lit slots are shown, dark ones stay hidden", pool.Lamps.All(l => l.Visible == (l.LightEnergy > 0f))
                   && pool.Lamps.Any(l => l.Visible), string.Join(",", pool.Lamps.Select(l => $"{l.LightEnergy}:{l.Visible}")));
            // Gain 0.5: lamp 1 (no flicker) 2 · 0.5 / π = 0.3183098861837907 (Task 21: Godot energy = three intensity / π).
            var l0 = pool.Lamps[0];
            Expect("P3 lamp slot 0", Math.Abs(l0.LightEnergy - 0.31830989f) < 1e-6 && l0.Position.DistanceTo(new Vector3(65, 5.90625f, 120)) < 1e-5
                   && l0.OmniRange == 4f && l0.OmniAttenuation == 2f && !l0.ShadowEnabled, $"{l0.LightEnergy} {l0.Position}");
            Expect("P3 night lamp at full night gain", Math.Abs(pool.Lamps[1].LightEnergy - 0.31830989f) < 1e-6, $"{pool.Lamps[1].LightEnergy}");
            float candle = pool.Lamps[2].LightEnergy / 0.31830989f;
            Expect("P3 candle within ±8 %", candle >= 0.92f - 1e-5 && candle <= 1.08f + 1e-5, $"{candle}");
            var fire = pool.Lamps[3].LightColor;
            Expect("P3 fire colour between #ffb35c and #ff6a20", fire.G <= new Color("ffb35c").G + 1e-5 && fire.G >= new Color("ff6a20").G - 1e-5, $"{fire}");
            var halo4 = pool.HaloOf(Rec("lamp-4").LightId!)!;
            var halo2 = pool.HaloOf(Rec("lamp-2").LightId!)!;
            Expect("P3 halos", halo4.Visible && halo2.Visible && ((QuadMesh)halo4.Mesh).Size.IsEqualApprox(new Vector2(0.24f, 0.24f))
                   && pool.HaloOf(Rec("lamp-1").LightId!) is null, "");
            builder.TickProps(0.2, null, focus, 0);
            Expect("P3 day: lamp 8 takes night-lamp 2's slot", pool.State.Selected.SequenceEqual(new[] { "1", "8", "4", "5", "6", "7" }),
                   string.Join(",", pool.State.Selected));
            Expect("P3 day: the night lamp's halo goes", !halo2.Visible && halo4.Visible, "");
            Expect("P3 storey switch", builder.SetLevel("loc-room", -1), "");
            builder.TickView(0.01, camera.GlobalPosition);
            builder.TickProps(0.2, null, focus, 1);
            Expect("P3 cellar storey: only lamp 3", pool.State.Selected.SequenceEqual(new[] { "3" }), string.Join(",", pool.State.Selected));
            Expect("P3 the parlour's halos hide", !halo4.Visible && !halo2.Visible, "");
            builder.SetLevel("loc-room", 0);
            builder.TickView(0.01, camera.GlobalPosition);

            // ---- P4 doors ----
            var door = Rec("door:0").Door!;
            var pivot = door.SwingNode!;
            var leaf = pivot.GetChild<Node3D>(0);
            Expect("P4 leaf pivot", pivot.Name == DoorProps.LeafPivotNode && pivot.Position.DistanceTo(new Vector3(0.05f, 0, 0)) < 1e-6
                   && leaf.Name == DoorProps.LeafNode && (leaf.Position + pivot.Position).Length() < 1e-6 && door.SwingAxis == Vector3.Up, "");
            Expect("P4 threshold", door.Swing == 1 && door.Level == 0 && door.At == new Scatter.P2(0, -5) && door.Rooms.SequenceEqual(new[] { "r-parlour" }), "");
            builder.TickProps(1.0 / 60, null, focus, 1);
            Expect("P4 shut in the overview", door.Angle == 0 && pivot.Basis == Basis.Identity, $"{door.Angle}");
            DoorProps.Tick(door, 1.0 / 60, 1.0);
            Expect("P4 an avatar 1 m away swings it 0.05 rad", Math.Abs(door.Angle - 0.05) < 1e-12
                   && pivot.Basis.IsEqualApprox(new Basis(Vector3.Up, 0.05f)), $"{door.Angle}");
            builder.TickProps(1.0 / 60, null, focus, 1);
            Expect("P4 and it eases shut again", door.Angle == 0 && pivot.Basis == Basis.Identity, $"{door.Angle}");

            // ---- P5 ambience ----
            SceneAmbience? At(double lx, double lz, string? open = "loc-room") => builder.AmbienceAt(open, new Vector3((float)(64 + lx), 5, (float)(120 + lz)));
            Expect("P5 parlour", At(0, 0) is { Daylight: 0.4, Tint: "#ffcf9a" }, $"{At(0, 0)}");
            Expect("P5 closet (smaller rect, no ambience)", At(3, 3) is null, $"{At(3, 3)}");
            Expect("P5 corridor outside the rooms", At(5.5, 5.5) is { Daylight: 0.8, Tint: "" }, $"{At(5.5, 5.5)}");
            Expect("P5 cellar rect (any storey)", At(-4, -4) is { Daylight: 0.2, Tint: "#8899ff" }, $"{At(-4, -4)}");
            Expect("P5 not the open location", At(0, 0, null) is null && At(0, 0, "loc-x") is null, "");
            // The stage under the room ambience at noon (Task 21: base = the clock, energies = three intensity / π;
            // noon: sun 2.25, fill 0.55, hemi 1.55 — fixtures/README "Light").
            var stageHost = new Node3D { Name = "PropsStage" };
            host.AddChild(stageHost);
            var stage = StageAmbience.Build(stageHost);
            stage.SetHour(12);
            var noonSun = stage.Sun.LightColor;
            var target = Ambience.Target(At(0, 0));
            var amb = Ambience.Step(AmbienceState.Neutral, target, 0.5);
            stage.Apply(amb);
            var sun = stage.Sun;
            // k = 1 − 1/e: daylight 1 − 0.6k = 0.6207276647028654 → sun 2.25·d/π = 0.44456, fill 0.55·d/π = 0.10867,
            // ambient 1.55·d/π = 0.30625.
            Expect("P5 one τ towards the parlour", Math.Abs(sun.LightEnergy - 0.44456344f) < 1e-6 && Math.Abs(stage.Fill.LightEnergy - 0.10867106f) < 1e-6
                   && Math.Abs(stage.Env.AmbientLightEnergy - 0.30625482f) < 1e-6 && Math.Abs(amb.G - 0.881012600691095) < 1e-12
                   && Math.Abs(amb.B - 0.7496306806208457) < 1e-12, $"{sun.LightEnergy} {stage.Fill.LightEnergy} {stage.Env.AmbientLightEnergy}");
            Expect("P5 tinted in linear space (red stays, green drops)", Math.Abs(sun.LightColor.R - 1f) < 1e-5
                   && sun.LightColor.G < noonSun.G - 0.01f, $"{sun.LightColor}");
            for (int i = 0; i < 4; i++) amb = Ambience.Step(amb, Ambience.Target(At(3, 3)), 0.125);
            stage.Apply(amb);
            // Back towards neutral for 4 × 0.125 = one τ: 1 − (1 − 0.62073)/e = 0.8604735052391023 → sun 2.25·d/π = 0.61627.
            Expect("P5 back towards neutral", Math.Abs(amb.Daylight - 0.8604735052391023) < 1e-12 && Math.Abs(sun.LightEnergy - 0.61626875f) < 1e-6,
                   $"{amb.Daylight}");
            stageHost.QueueFree();

            // ---- P6 lamps follow the re-lift ----
            builder.Height!.AddTiles(new[] { new HeightTile((0, 0), new HeightGrid(0, 0, 64, 5, 5, Enumerable.Repeat(10f, 25).ToArray())) });
            builder.TickModels(camera.GlobalPosition);
            Expect("P6 lamp 1 on the flat tile: 10 + 0 + 2", Close(pool.State.PositionOf(Rec("lamp-1").LightId!)!.Value, 65, 12, 120, 1e-5),
                   $"{pool.State.PositionOf(Rec("lamp-1").LightId!)}");

            // ---- P7 the world clock ----
            using var map = JsonDocument.Parse(File.ReadAllBytes(Path.Combine(dir, "worldmap.json")));
            var hour = Ambience.GameHourOf(map.RootElement);
            Expect("P7 22:00 → night 1", hour == 22 && Ambience.NightFactorAt(hour!.Value) == 1, $"{hour}");

            return $"props P1..P7 ok (slots picture+glass on cut clones, mirrors {mirrors.Panes.Count} panes {string.Join(" ", sets)}, "
                   + $"lights {pool.State.Count} sources night 1,2,4,5,6,7 / day 1,8,4,5,6,7 / cellar 3, door pivot, ambience 0.62073→0.86047, {stats.CutSummary()})";
        }
        finally
        {
            builder.Models?.FreeAll();
            camera.QueueFree();
            world.QueueFree();
        }
    }

    private static bool IsUnder(Node n, Node root) => n == root || root.IsAncestorOf(n);

    private static bool Close(Overview.Vec3 v, double x, double y, double z, double eps)
        => Math.Abs(v.X - x) < eps && Math.Abs(v.Y - y) < eps && Math.Abs(v.Z - z) < eps;

    private static MeshInstance3D? FirstMesh(Node n)
    {
        if (n is MeshInstance3D mi) return mi;
        foreach (var c in n.GetChildren())
            if (FirstMesh(c) is { } m) return m;
        return null;
    }

    private static void Near(string what, double got, double want)
        => Expect(what, Math.Abs(got - want) < 1e-4, $"got {got}, expected {want}");

    private static void Eq(string what, int got, int want) => Expect(what, got == want, $"got {got}, expected {want}");

    private static void Expect(string what, bool ok, string detail)
    {
        if (!ok) throw new InvalidOperationException($"props {what}: {detail}");
    }
}
