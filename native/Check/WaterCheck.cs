using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using AnimaNative.Ground;
using AnimaNative.Scatter;
using AnimaNative.Water;
using AnimaNative.World;
using Godot;

namespace AnimaNative.Check;

/// <summary>
/// <c>--check water</c> (part of every <c>--check</c>, Task 25): the water beside and on the terrain against numbers
/// derived by hand in native/fixtures/README.md "Water (Task 25)", on the real Godot objects:
///
///   W0 the shaders: the terrain's water variant, the waterfall curtain and foam, the prop water sheet and the three
///      ghost variants compile; the texts say what the browser's do (one sd field for lift and look, the wave map read
///      as three's flipped canvas, the inverted depth test);
///   W1 the shore gradient and the foam band at sample depths (opaque depth 1.5 m, rim 5 cm, foam band 0.6 m);
///   W2 the waterfalls of fixtures/water/terrain.json: one fall (the polygon lake and the zero-area sliver have none),
///      its curtain corners, uvs, scroll and tiles read back from the mesh and the material, its foam disc;
///   W3 the underwater ghost: nothing built while dry, one twin per surface under the mesh it doubles (same mesh, the
///      skeleton of a skinned one), the waterline cut, the switch; the figure gate at the fixture's mirror;
///   W4 the prop water sheets of fixtures/water/prop_spec.json at region.y + lift, their triangles, look and re-lift,
///      the material cache, the hour's sky.
/// </summary>
public static class WaterCheck
{
    private const double Eps = 1e-6;

    public static string Run(Node3D host, string fixtures)
    {
        var root = new Node3D { Name = "WaterCheck" };
        host.AddChild(root);
        try
        {
            var dir = Path.Combine(fixtures, "water");
            var w0 = Shaders();
            var w1 = Shore();
            var w2 = Falls(root, dir);
            var w3 = Ghost(root, dir);
            var w4 = Sheets(root, dir);
            return $"water W0..W4 ok ({w0}; {w1}; {w2}; {w3}; {w4})";
        }
        finally
        {
            bool off = SubmergedGhost.Off;
            root.QueueFree();
            SubmergedGhost.Off = off;
        }
    }

    // ---- W0 ----

    private static string Shaders()
    {
        var names = new List<string>();
        void Compiled(Shader s, string name)
        {
            Expect($"W0 {name} compiles", ShaderSafety.Ok(s, name), string.Join(" | ", ShaderSafety.Lines));
            names.Add(name);
        }
        Compiled(GroundShader.Get(true), "ground-water");
        Compiled(WaterfallLayer.CurtainShader(), "waterfall-curtain");
        Compiled(WaterfallLayer.FoamShader(), "waterfall-foam");
        Compiled(PropWaterSheets.Shader(), "prop-water");
        foreach (var c in new[] { BaseMaterial3D.CullModeEnum.Back, BaseMaterial3D.CullModeEnum.Disabled, BaseMaterial3D.CullModeEnum.Front })
            Compiled(SubmergedGhost.ShaderFor(c), $"water-ghost[{c.ToString().ToLowerInvariant()}]");

        var wet = GroundShader.Code(true);
        Expect("W0 the look reads the lift's sd field (one field, finding G1)", wet.Contains("float inside = tl_inside(tl_sd_at(p));")
               && !wet.Contains("tw_sd") && !wet.Contains("tw_geom") && wet.Contains("(p.x - tl_water_geom.x) / stp"), "");
        Expect("W0 the terrain ripple reads three's flipped canvas", wet.Contains("vec2 f = vec2(1.0, -1.0);")
               && wet.Contains("textureGrad(tw_wave, uv * f, gx * f, gy * f)"), "");
        Expect("W0 the curtain reads three's flipped canvas", WaterfallLayer.CurtainCode().Contains("texture(wf_map, vec2(s.x, -s.y))"), "");
        Expect("W0 the sheet reads three's flipped canvas", PropWaterSheets.Code().Contains("texture(pw_wave, vec2(uv.x, -uv.y))"), "");
        foreach (var c in new[] { "cull_back", "cull_disabled", "cull_front" })
        {
            var g = SubmergedGhost.Code(c switch
            {
                "cull_disabled" => BaseMaterial3D.CullModeEnum.Disabled,
                "cull_front" => BaseMaterial3D.CullModeEnum.Front,
                _ => BaseMaterial3D.CullModeEnum.Back,
            });
            Expect($"W0 ghost {c}: inverted depth test, no depth write, unshaded, 0.4, the cut",
                   g.Contains($"render_mode unshaded, blend_mix, depth_draw_never, depth_test_inverted, {c}")
                   && g.Contains("float a = 0.4 * m.a;") && g.Contains("if (v_ghost_y > ghost_cut_y) discard;"), "");
        }
        return $"shaders {names.Count}";
    }

    // ---- W1 ----

    /// <summary>README "Water (Task 25)" W1: inside 1, opaque 1.5 m, rim 5 cm.</summary>
    private static string Shore()
    {
        var table = new (double D, double A, double S, double Foam)[]
        {
            (0.025, 0.000412037, 0.1752678241, 0.0746523251),
            (0.05, 0.0032592593, 0.3521185185, 0.1473504238),
            (0.1, 0.0127407407, 0.3582814815, 0.1403978052),
            (0.3, 0.104, 0.4176, 0.0895),
            (0.59, 0.3424272593, 0.5725777185, 0.0002822873),
            (0.6, 0.352, 0.5788, 0),
            (0.75, 0.5, 0.675, 0),
            (1.5, 1, 1, 0),
            (2.0, 1, 1, 0),
        };
        foreach (var (d, a, s, foam) in table)
        {
            NearD($"W1 absorb at {d} m", WaterShade.Absorb(d, 1.5, 0.05), a, 1e-9);
            NearD($"W1 surface at {d} m", WaterShade.Surface(d, 0.05, 1, 1.5), s, 1e-9);
            NearD($"W1 foam at {d} m", WaterShade.FoamAt(d, 1.5, 0.05), foam, 1e-9);
        }
        // The band edges: the foam is gone exactly at 0.6 m, the bed exactly at 1.5 m, the rim is up exactly at 5 cm.
        Expect("W1 foam band edge 0.6 m", WaterShade.FoamAt(0.6, 1.5, 0.05) == 0 && WaterShade.FoamAt(0.5999, 1.5, 0.05) > 0, "");
        Expect("W1 opaque edge 1.5 m", WaterShade.Absorb(1.5, 1.5, 0.05) == 1 && WaterShade.Absorb(1.4999, 1.5, 0.05) < 1, "");
        Expect("W1 rim edge 5 cm", WaterShade.EdgeFade(0.05, 0.05) == 1 && WaterShade.EdgeFade(0.0499, 0.05) < 1, "");
        return "shore 9 depths, edges 0.05/0.6/1.5";
    }

    // ---- W2 ----

    private static TerrainPayload Terrain(string dir)
    {
        using var doc = JsonDocument.Parse(File.ReadAllText(Path.Combine(dir, "terrain.json")));
        return TerrainPayload.Parse(doc.RootElement);
    }

    private static string Falls(Node3D root, string dir)
    {
        var terrain = Terrain(dir);
        Expect("W2 the sliver has a fall of its own (skipped only for its ring)", terrain.Areas[3].Falls.Count == 1
               && ScatterMath.AreaRing(terrain.Areas[3].Polygon) is null, "");
        var layer = new WaterfallLayer();
        root.AddChild(layer);
        int n = layer.Rebuild(terrain);
        Expect("W2 one fall: the river's (lake: no stroke; sliver: no ring)", n == 1 && layer.Meshes.Count == 2,
               $"{n} falls, {layer.Meshes.Count} meshes");
        Expect("W2 the fall", layer.Falls[0] == new Waterfall(11, 22, 1, 0, 4, 10, 6, 2), layer.Falls[0].ToString());

        var curtain = layer.Meshes[0];
        var arrays = ((ArrayMesh)curtain.Mesh).SurfaceGetArrays(0);
        var pos = arrays[(int)Mesh.ArrayType.Vertex].AsVector3Array();
        var uv = arrays[(int)Mesh.ArrayType.TexUV].AsVector2Array();
        var want = new[] { new Vector3(10, 10, 24), new Vector3(10, 10, 20), new Vector3(13.2f, 6, 24), new Vector3(13.2f, 6, 20) };
        Expect("W2 curtain corners lip-left, lip-right, foot-left, foot-right",
               pos.Length == 4 && pos.Zip(want).All(p => p.First.DistanceTo(p.Second) < 1e-5f), string.Join(" ", pos));
        Expect("W2 curtain uvs (v 1 at the lip)", uv.SequenceEqual(new[] { new Vector2(0, 1), new Vector2(1, 1), new Vector2(0, 0), new Vector2(1, 0) }),
               string.Join(" ", uv));
        var mat = (ShaderMaterial)curtain.MaterialOverride;
        NearD("W2 scroll tiles/s √(9.81·4/2)/2.5", (float)mat.GetShaderParameter("wf_speed"), 1.771778767, 1e-6);
        Expect("W2 tiles (1.6, 1.6)", mat.GetShaderParameter("wf_tiles").AsVector2().DistanceTo(new Vector2(1.6f, 1.6f)) < 1e-6f, "");
        Expect("W2 the wave map is THE one", mat.GetShaderParameter("wf_map").As<Texture2D>() == GroundSurfaces.WaveTexture, "");
        Expect("W2 no shadows", curtain.CastShadow == GeometryInstance3D.ShadowCastingSetting.Off, "");

        var foam = layer.Meshes[1];
        var fa = ((ArrayMesh)foam.Mesh).SurfaceGetArrays(0);
        var fp = fa[(int)Mesh.ArrayType.Vertex].AsVector3Array();
        var fc = fa[(int)Mesh.ArrayType.Color].AsColorArray();
        var fi = fa[(int)Mesh.ArrayType.Index].AsInt32Array();
        Expect("W2 foam disc: centre at the foot + 5 cm, alpha 0.6, rim 2 m alpha 0, 24 triangles wound for Godot",
               fp.Length == 26 && fp[0].DistanceTo(new Vector3(13.2f, 6.05f, 22)) < 1e-5f && Math.Abs(fc[0].A - 0.6f) < 1e-6f
               && fp[1].DistanceTo(new Vector3(15.2f, 6.05f, 22)) < 1e-5f && fc[1].A == 0
               && fp[7].DistanceTo(new Vector3(13.2f, 6.05f, 20)) < 1e-5f && fi.Length == 72 && fi.Take(3).SequenceEqual(new[] { 1, 0, 2 }),
               $"{fp.Length} {fp[0]} {fp[1]} {fp[7]} {string.Join(",", fi.Take(3))}");
        // A new terrain payload replaces the falls (rebuildAreas).
        using var empty = JsonDocument.Parse("{\"areas\": []}");
        Expect("W2 a new payload replaces them", layer.Rebuild(TerrainPayload.Parse(empty.RootElement)) == 0 && layer.Meshes.Count == 0, "");
        return "falls 1 (corners (10,10,24) (10,10,20) (13.2,6,24) (13.2,6,20), 1.7718 tiles/s, foam r 2 at y 6.05)";
    }

    // ---- W3 ----

    private static string Ghost(Node3D root, string dir)
    {
        SubmergedGhost.Off = false;
        var obj = new Node3D { Name = "Crate" };
        root.AddChild(obj);
        var img = Image.CreateEmpty(2, 2, false, Image.Format.Rgba8);
        img.Fill(new Color(0.5f, 0.5f, 0.5f));
        var tex = ImageTexture.CreateFromImage(img);
        var box = new MeshInstance3D
        {
            Name = "Box",
            Mesh = new BoxMesh(),
            MaterialOverride = new StandardMaterial3D
            {
                AlbedoTexture = tex, CullMode = BaseMaterial3D.CullModeEnum.Disabled,
                Transparency = BaseMaterial3D.TransparencyEnum.AlphaScissor, AlphaScissorThreshold = 0.5f,
            },
        };
        obj.AddChild(box);
        var ghost = new SubmergedGhost(obj);
        ghost.Set(null);
        Expect("W3 a dry object builds nothing", ghost.Count == 0 && box.GetChildCount() == 0, "");
        // The fixture's lake: 5 m over a crate whose base is 4.6 → submerged (0.4 ≥ 0.05) → cut at 5.
        double? cut = WaterGates.GhostCutY(4.6, Terrain(dir).WaterLevelAt(10, 0));
        Expect("W3 the gate at the lake: cut 5", cut == 5, $"{cut}");
        ghost.Set(cut);
        var twin = ghost.Parts.Single();
        var gm = ghost.Materials.Single();
        Expect("W3 one twin under the mesh it doubles, same mesh, no transform of its own, no shadow",
               twin.GetParent() == box && twin.Mesh == box.Mesh && twin.Transform == Transform3D.Identity && twin.Visible
               && twin.CastShadow == GeometryInstance3D.ShadowCastingSetting.Off && twin.HasMeta(SubmergedGhost.Meta), "");
        Expect("W3 the ghost material: its texture, the side, the scissor, the waterline",
               gm.Shader == SubmergedGhost.ShaderFor(BaseMaterial3D.CullModeEnum.Disabled)
               && gm.GetShaderParameter("ghost_map").As<Texture2D>() == tex && (float)gm.GetShaderParameter("ghost_has_map") == 1f
               && Math.Abs((float)gm.GetShaderParameter("ghost_alpha_test") - 0.5f) < 1e-6f
               && (float)gm.GetShaderParameter("ghost_cut_y") == 5f
               && gm.GetShaderParameter("ghost_tint").AsVector3().DistanceTo(new Vector3(63 / 255f, 127 / 255f, 184 / 255f)) < 1e-6f, "");
        ghost.Set(5.75);
        Expect("W3 a rising lake moves the cut, builds nothing new", ghost.Count == 1 && (float)gm.GetShaderParameter("ghost_cut_y") == 5.75f, "");
        ghost.Set(null);
        Expect("W3 dry again: hidden, kept", ghost.Count == 1 && !twin.Visible && !ghost.Visible, "");
        SubmergedGhost.Off = true;
        ghost.Set(5);
        Expect("W3 the switch (--no-water) hides it", !twin.Visible, "");
        SubmergedGhost.Off = false;
        ghost.Reapply();
        Expect("W3 …and gives it back", twin.Visible, "");

        // A skinned mesh: the twin binds the SAME skeleton.
        var skel = new Skeleton3D { Name = "Skeleton3D" };
        skel.AddBone("root");
        var fig = new Node3D { Name = "Fig" };
        root.AddChild(fig);
        fig.AddChild(skel);
        var skin = new Skin();
        skin.AddBind(0, Transform3D.Identity);
        var body = new MeshInstance3D { Name = "Body", Mesh = new BoxMesh(), Skin = skin };
        skel.AddChild(body);
        body.Skeleton = body.GetPathTo(skel);
        var fg = new SubmergedGhost(fig);
        fg.Set(1);
        var ft = fg.Parts.Single();
        Expect("W3 skinned: same skin, same skeleton", ft.Skin == skin && ft.GetNodeOrNull(ft.Skeleton) == skel, $"{ft.Skeleton}");

        // The figure gate (npcs.ts): the river's mirror 10 over a bed at 9 → 10; inside a built place → dry; on the sandbank → dry.
        var t = Terrain(dir);
        Expect("W3 figure gate: river 10 over bed 9", WaterGates.GhostCutY(9, WaterGates.GroundWaterLevel(t.WaterLevelAt(5, 22), GroundScope.Wilderness)) == 10, "");
        Expect("W3 figure gate: built → dry", WaterGates.GhostCutY(9, WaterGates.GroundWaterLevel(t.WaterLevelAt(5, 22), GroundScope.Built)) is null, "");
        Expect("W3 figure gate: the sandbank over the lake → dry", WaterGates.GhostCutY(4, t.WaterLevelAt(32, 0)) is null, "");
        return "ghost cut 5 → 5.75, 1 twin, skinned bound, gates 10/built/bank";
    }

    // ---- W4 ----

    private static string Sheets(Node3D root, string dir)
    {
        using var doc = JsonDocument.Parse(File.ReadAllText(Path.Combine(dir, "prop_spec.json")));
        var spec = ScenePayload.ParseModel(doc.RootElement);
        Expect("W4 two regions parsed", spec.Water.Length == 2, $"{spec.Water.Length}");
        var parent = new Node3D { Name = "Placement" };
        root.AddChild(parent);
        int before = PropWaterSheets.Built;
        var sheets = PropWaterSheets.Build(spec.Water, parent, 0.25);
        Expect("W4 one sheet per region, in the parent", sheets.Count == 2 && PropWaterSheets.Built == before + 2
               && sheets.All(s => s.GetParent() == parent && s.HasMeta(PropWaterSheets.Meta)), "");
        NearD("W4 sheet 0 at y + lift = 1.5 + 0.25", sheets[0].Position.Y, 1.75, Eps);
        NearD("W4 sheet 1 at 2 + 0.25", sheets[1].Position.Y, 2.25, Eps);
        int Tris(MeshInstance3D m) => ((ArrayMesh)m.Mesh).SurfaceGetArrays(0)[(int)Mesh.ArrayType.Index].AsInt32Array().Length / 3;
        Expect("W4 triangles: square with a hole 8, square 2", Tris(sheets[0]) == 8 && Tris(sheets[1]) == 2, $"{Tris(sheets[0])}/{Tris(sheets[1])}");
        var mat = (ShaderMaterial)sheets[0].MaterialOverride;
        Expect("W4 one material per tint|opacity", mat == sheets[1].MaterialOverride && mat == PropWaterSheets.MaterialFor("#3f7fb8", 0.7), "");
        Expect("W4 look: albedo 0.25·raw + 0.75·linear, opacity 0.7",
               mat.GetShaderParameter("pw_albedo").AsVector3().DistanceTo(new Vector3(0.0990446f, 0.2836829f, 0.5398823f)) < 1e-6f
               && Math.Abs((float)mat.GetShaderParameter("pw_opacity") - 0.7f) < 1e-6f, mat.GetShaderParameter("pw_albedo").ToString());
        PropWaterSheets.Relift(sheets, spec.Water, 1.0);
        NearD("W4 a re-lift moves it: 1.5 + 1", sheets[0].Position.Y, 2.5, Eps);
        var sky = new Vector3(116 / 255f, 146 / 255f, 170 / 255f);
        PropWaterSheets.SetSky(sky);
        Expect("W4 the hour's sky reaches every sheet", mat.GetShaderParameter("pw_sky").AsVector3() == sky, "");
        PropWaterSheets.SetSky(new Vector3((float)WaterShade.Sky.R, (float)WaterShade.Sky.G, (float)WaterShade.Sky.B));
        // The walk side of the same regions (vector-checked in dotnet test): the overlap reads the higher mirror.
        var hit = PropWater.WaterRegionAt(new[] { spec }, 3.5, 3.5, _ => 0.25);
        Expect("W4 region at (3.5, 3.5): the higher mirror 2 + 0.25", hit is { } h && Math.Abs(h.Y - 2.25) < Eps && Math.Abs(h.BedY - 1.75) < Eps, $"{hit}");
        return "sheets 2 at 1.75/2.25 → 2.5, triangles 8/2, albedo (0.0990, 0.2837, 0.5399)";
    }

    private static void NearD(string what, double got, double want, double eps)
        => Expect(what, Math.Abs(got - want) <= eps, $"got {got}, expected {want}");

    private static void Expect(string what, bool ok, string detail)
    {
        if (!ok) throw new InvalidOperationException($"{what}: {detail}");
    }
}
