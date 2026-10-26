using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using AnimaNative.Scatter;
using AnimaNative.Scene;
using AnimaNative.Sky;
using AnimaNative.World;
using Godot;

namespace AnimaNative.Check;

/// <summary>
/// <c>--check shadow</c> (part of every <c>--check</c>, Task 26c): the browser's shadow casters, the cheaper fog and
/// light paths, read back from live nodes:
///
///   H1 caster classes on the S3c world (README "S3c world"): world props cast nothing; inside an interior a recipe
///      plate casts only on a storey above ground with a thickness (loc-open: its level-1 slab 0.2 m and room plate
///      0.02 m — tags slab1 / plate1; the rule itself on level 1/0/−1 × thickness 0.2/0), walls, extras, placements and stand-ins never; outside the interior everything
///      follows the shell flag (on at fade 0, off at fade 1); a location group WITHOUT an interior keeps its
///      construction flags at any fade (applyTileFade returns early);
///   H2 the caster gate: the sun casts from the gate's layer only; after a pass at loc-open its shell (building model,
///      outdoor plate) carries it, a caster 300 m away and a hemisphere-layer node do not; the switch off gives every caster the layer, back on
///      takes it away again; a node that leaves the tree leaves the registry;
///   H3 the cluster budget is 32 elements per type (≥ the six-lamp pool), the scatter shader carries the hemisphere term
///      and its material is bound; the distance fog's compute pass is the default (<c>--fog=pass</c> the fallback), the
///      pass quad sits on its own layer, and headless (no RenderingDevice) the overview camera still draws it.
/// </summary>
public static class ShadowCheck
{
    public static async Task<string> RunAsync(Node3D host, string fixtures)
    {
        var dir = Path.Combine(fixtures, "s3c");
        var source = new FixtureSource(dir, fixtures);
        var root = new Node3D { Name = "ShadowCheck" };
        host.AddChild(root);
        var world = new Node3D { Name = "World" };
        root.AddChild(world);
        var gate = new ShadowCasterGate();
        WorldBuilder? built = null;
        try
        {
            var builder = new WorldBuilder(source, line => GD.Print("[check-shadow] " + line), strict: true);
            built = builder;
            await builder.BuildAsync(world, "Glass");

            // ---- H1 classes ----
            const GeometryInstance3D.ShadowCastingSetting On = GeometryInstance3D.ShadowCastingSetting.On;
            var worldProps = Meshes(world.GetNode("WorldProps")).ToList();
            Expect("H1 world props cast nothing", worldProps.Count > 0 && worldProps.All(g => g.CastShadow != On), $"{worldProps.Count}");
            var slot = builder.Slots["loc-open"];
            var interior = slot.Fade.Interior!;
            var inside = Meshes(interior).ToList();
            var recipe = inside.Where(g => g.Name.ToString().StartsWith("Recipe_", StringComparison.Ordinal)).ToList();
            string Tag(Node g) => g.Name.ToString().Split('_')[1];
            var casting = recipe.Where(g => g.CastShadow == On).Select(Tag).Distinct().OrderBy(t => t).ToList();
            Expect("H1 interior: only the upper storey's thick plates cast", casting.SequenceEqual(new[] { "plate1", "slab1" }),
                   string.Join(",", casting));
            Expect("H1 interior: walls and extras do not", recipe.Where(g => Tag(g).StartsWith("wall") || Tag(g) == "other")
                   .All(g => g.CastShadow != On) && recipe.Any(g => Tag(g).StartsWith("wall")), "");
            static ScenePlate Plate(int level, double thickness) => new(level, Array.Empty<(double, double)>(),
                                                                         Array.Empty<(double, double)[]>(), 0, thickness);
            Expect("H1 the plate rule: level > 0 AND thickness > 0", RecipeMeshes.PlateCasts(Plate(1, 0.2))
                   && !RecipeMeshes.PlateCasts(Plate(1, 0)) && !RecipeMeshes.PlateCasts(Plate(0, 0.2))
                   && !RecipeMeshes.PlateCasts(Plate(-1, 0.2)), "");
            var placed = inside.Where(g => !g.Name.ToString().StartsWith("Recipe_", StringComparison.Ordinal)).ToList();
            Expect("H1 interior: placements and stand-ins do not", placed.Count > 0 && placed.All(g => g.CastShadow != On),
                   string.Join(",", placed.Where(g => g.CastShadow == On).Select(g => g.GetPath())));
            var shell = Meshes(slot.Group).Where(g => !interior.IsAncestorOf(g) && !g.HasMeta(LocationFade.OverlayMeta)).ToList();
            slot.Fade.Snap(0);
            Expect("H1 shell casts at fade 0", shell.Count > 0 && shell.All(g => g.CastShadow == On), $"{shell.Count}");
            slot.Fade.Snap(1);
            Expect("H1 shell stops at fade 1", shell.All(g => g.CastShadow != On), "");
            slot.Fade.Snap(0);
            Expect("H1 the interior keeps its flags through the fade", recipe.Where(g => g.CastShadow == On).Select(Tag).Distinct()
                   .OrderBy(t => t).SequenceEqual(new[] { "plate1", "slab1" }), "");

            var bare = new Node3D { Name = "Bare" };
            var model = new MeshInstance3D { Name = "Model", Mesh = new BoxMesh() };
            var prop = new MeshInstance3D { Name = "Prop", Mesh = new BoxMesh(), CastShadow = GeometryInstance3D.ShadowCastingSetting.Off };
            bare.AddChild(model);
            bare.AddChild(prop);
            root.AddChild(bare);
            var noInterior = new LocationFade();
            noInterior.Collect(bare);
            noInterior.Snap(1);
            noInterior.Snap(0);
            Expect("H1 without an interior the construction flags stand", model.CastShadow == On && prop.CastShadow != On, "");

            // ---- H2 the gate ----
            var stage = StageAmbience.Build(root);
            stage.SetHour(12);
            gate.Attach(world);
            stage.Gate = gate;
            Expect("H2 the sun casts from the gate's layer only", stage.Sun.ShadowCasterMask == ShadowCasterGate.Layer,
                   $"{stage.Sun.ShadowCasterMask:x}");
            var far = new MeshInstance3D { Name = "FarCaster", Mesh = new BoxMesh() };
            var hemi = new MeshInstance3D { Name = "HemiNode", Mesh = new BoxMesh(), Layers = HemiUniforms.Layer };
            world.AddChild(far);
            world.AddChild(hemi);
            var at = slot.Group.Position;
            far.Position = at + new Vector3(300, 0, 0);
            hemi.Position = at;
            stage.Track(at, 40);
            bool Has(GeometryInstance3D g) => (g.Layers & ShadowCasterGate.Layer) != 0;
            Expect("H2 a pass ran over the registry", gate.Passes >= 1 && gate.Registered > 0, $"{gate.Passes}/{gate.Registered}");
            Expect("H2 the shell at the target (building model, outdoor plate) carries the layer", shell.All(Has),
                   string.Join(",", shell.Where(g => !Has(g)).Select(g => g.GetParent()?.Name + "/" + g.Name)));
            Expect("H2 300 m away: no layer", !Has(far), "");
            Expect("H2 the hemisphere layer never gets it", !Has(hemi) && hemi.Layers == HemiUniforms.Layer, "");
            Expect("H2 non-casters are skipped", worldProps.All(g => !Has(g)), "");
            int insideBox = gate.Inside;
            gate.Off = true;
            gate.MarkPass();
            Expect("H2 switch off: every caster carries the layer", Has(far) && gate.Inside > insideBox && !Has(hemi), $"{gate.Inside}");
            gate.Off = false;
            gate.MarkPass();
            Expect("H2 back on: the far caster drops it", !Has(far) && gate.Inside == insideBox, $"{gate.Inside} vs {insideBox}");
            int registered = gate.Registered;
            world.RemoveChild(far);
            far.Free();
            Expect("H2 a node that leaves the tree leaves the registry", gate.Registered == registered - 1, $"{gate.Registered}");

            // ---- H3 lights, scatter, fog ----
            int clustered = ProjectSettings.GetSetting("rendering/limits/cluster_builder/max_clustered_elements").AsInt32();
            Expect("H3 cluster budget 32 ≥ the lamp pool", clustered == 32 && clustered >= PropLights.PoolSize, $"{clustered}");
            var tuft = ScatterShaders.Tuft("#6a8f3a", 0.2, 1);
            Expect("H3 scatter material carries the hemisphere term", HemiUniforms.Materials().Contains(tuft)
                   && tuft.GetShaderParameter(HemiUniforms.Uniform).AsVector3() == HemiUniforms.Value
                   && ScatterShaders.Code(0, true, false, false, true)
                       .Contains("EMISSION = c.rgb * (1.0 - metallic_v) * av_hemi * normalize((INV_VIEW_MATRIX * vec4(NORMAL, 0.0)).xyz).y;"), "");
            Expect("H3 the compute fog is the default, --fog=pass the fallback", CliOptions.Parse(Array.Empty<string>()).FogCompute
                   && !CliOptions.Parse(new[] { "--fog=pass" }).FogCompute && CliOptions.Parse(new[] { "--fog=compute" }).FogCompute, "");
            var camera = new Camera3D { Name = "FogCamera" };
            root.AddChild(camera);
            var fog = DistanceFog.Attach(camera, compute: true);
            fog.UseCompute = true;
            fog.Decide();
            Expect("H3 the pass quad on its own layer; headless the overview camera draws it", fog.Layers == DistanceFog.PassLayer
                   && !fog.ComputeActive && fog.PassInMainView && (camera.CullMask & DistanceFog.PassLayer) != 0, $"{fog.Layers:x}");
            fog.Off = true;
            fog.Decide();
            Expect("H3 fog off hides the quad", !fog.Visible && !fog.PassInMainView, "");

            return $"shadow H1..H3 ok (world props {worldProps.Count} off; loc-open interior casts {string.Join("+", casting)}, "
                   + $"shell {shell.Count} on/off with the fade; gate {gate.Registered} registered, {insideBox} in the box at loc-open, "
                   + $"pass {gate.LastPassMs:0.###} ms; clusters {clustered}; fog compute default, pass layer 18)";
        }
        finally
        {
            gate.Detach();
            built?.Models?.FreeAll();
            root.QueueFree();
        }
    }

    private static IEnumerable<GeometryInstance3D> Meshes(Node root)
    {
        if (root is GeometryInstance3D g) yield return g;
        foreach (var c in root.GetChildren())
            foreach (var m in Meshes(c)) yield return m;
    }

    private static void Expect(string what, bool ok, string detail)
    {
        if (!ok) throw new InvalidOperationException($"{what}: {detail}");
    }
}
