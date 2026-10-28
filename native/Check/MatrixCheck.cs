using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Threading.Tasks;
using AnimaNative.Bench;
using AnimaNative.Scene;
using AnimaNative.Sky;
using AnimaNative.World;
using Godot;

namespace AnimaNative.Check;

/// <summary>
/// <c>--check matrix</c> (part of every <c>--check</c>, Task 26b): the runtime switches of <c>--bench-matrix</c> on a
/// real world — the props fixture (cut clones, six-lamp pool, a mirror; README "Props") with the stage, the fog pass and
/// its compute twin under a camera, a backdrop ring and one ghost + one prop water sheet hung onto the world props'
/// water list — read back from the live nodes:
///
///   M0 the variant list: baseline first, every name has a switch, a subset keeps the baseline; the schedule puts a
///      baseline between every two variants and at both ends (Task 26c: drift);
///   M1 each variant switches exactly its feature (the light, the uniform, the node, the flag, the material);
///   M2 its restore puts back EVERYTHING the switches can touch (one snapshot of all of it equals the one taken before);
///   M3 the headless honesty: the compute fog has no RenderingDevice here, so the screen pass fogs anyway and the
///      <c>fog-pass</c> variant says "applied: false".
/// </summary>
public static class MatrixCheck
{
    public static async Task<string> RunAsync(Node3D host, string fixtures)
    {
        var dir = Path.Combine(fixtures, "props");
        var source = new FixtureSource(dir, fixtures);
        var root = new Node3D { Name = "MatrixCheck" };
        host.AddChild(root);
        var world = new Node3D { Name = "MatrixWorld" };
        root.AddChild(world);
        bool ghostOff = SubmergedGhost.Off;
        WorldBuilder? built = null;
        ShadowCasterGate? gate = null;
        try
        {
            // ---- M0 the list ----
            var names = BenchMatrix.Variants.Select(v => v.Name).ToList();
            Expect("M0 baseline first, every name once", names[0] == BenchMatrix.Baseline && names.Distinct().Count() == names.Count,
                   string.Join(",", names));
            var schedule = BenchMatrix.Schedule(BenchMatrix.Variants).Select(v => v.Name).ToList();
            Expect("M0 the schedule interleaves the baseline (B V B … V B)", schedule.Count == 2 * names.Count - 1
                   && schedule.Where((_, i) => i % 2 == 0).All(n => n == BenchMatrix.Baseline)
                   && schedule.Where((_, i) => i % 2 == 1).SequenceEqual(names.Skip(1)), string.Join(",", schedule));
            Expect("M0 a subset keeps the baseline in front", BenchMatrix.Select("no-shadow,no-veil").Select(v => v.Name)
                   .SequenceEqual(new[] { BenchMatrix.Baseline, "no-shadow", "no-veil" }), "");

            var stage = StageAmbience.Build(root);
            stage.SetHour(12);
            gate = new ShadowCasterGate();
            gate.Attach(root);
            stage.Gate = gate;
            var camera = new Camera3D { Name = "MatrixCamera" };
            root.AddChild(camera);
            var fog = DistanceFog.Attach(camera, compute: true);
            stage.Fog = fog;
            var backdrop = new WorldBackdrop { Name = "Backdrop" };
            world.AddChild(backdrop);
            using (var doc = JsonDocument.Parse("{\"backdrop\": {\"height_m\": 120, \"seed\": 7, \"arcs\": [[90, 135]]}}"))
                backdrop.Sync(BackdropSpec.Of(doc.RootElement));
            var builder = new WorldBuilder(source, line => GD.Print("[check-matrix] " + line), strict: true) { LightSeed = 7 };
            built = builder;
            await builder.BuildAsync(world, "Lamp House");
            await Task.WhenAll(builder.SlotLoads);
            await WorldPropWaterSwitch(builder);
            // Night at the room: the pool lights its lamps; a first mirror pass is granted (the props check's P3 / P4 path).
            var focus = builder.Slots["loc-room"].Group.Position + new Vector3(1, 1.5f, -8);
            camera.Position = focus + new Vector3(0, 0, 3);
            for (int i = 0; i < 3; i++) builder.TickProps(0.2, camera, focus, 1);
            // The veil at full strength: something for no-veil to take away.
            VeilUniforms.SetFogged(true);
            VeilUniforms.SetCameraHeight(45);
            // One underwater ghost and one prop water sheet on the world props' water list.
            var ghostRoot = new Node3D { Name = "GhostRoot" };
            ghostRoot.AddChild(new MeshInstance3D { Name = "Body", Mesh = new BoxMesh() });
            world.AddChild(ghostRoot);
            var ghost = new SubmergedGhost(ghostRoot);
            ghost.Set(0.25);
            var sheet = new MeshInstance3D { Name = "Sheet", Mesh = new PlaneMesh() };
            world.AddChild(sheet);
            var spec = new SceneModelSpec("prop", "ghost", "ghost", false, new Dictionary<string, string>(), null, 0, 0, 0, 0, 0, 1,
                                          "", null, 0, 0, 0);
            builder.WorldPropWater.Add((spec, ghostRoot, new List<MeshInstance3D> { sheet }, ghost));
            var scatter = new Scatter.ScatterLayer(source, builder.Height!, () => Vector3.Zero, _ => { });
            root.AddChild(scatter);
            var ctx = new BenchSwitchContext { Scatter = scatter, Stage = stage, Fog = fog, Backdrop = () => backdrop, Builder = builder, Gate = gate };
            fog.UseCompute = true;   // Main's default (Task 26c); headless the screen pass stays all the same
            fog.Decide();
            stage.Track(focus, 40);

            var pool = builder.PropLights!;
            var mirrors = builder.Mirrors!;
            var cuts = CutMaterials.LiveHandles().SelectMany(h => h.Entries).Where(e => IsInstanceValid(e.Mesh)).ToList();
            Expect("M1 the props world has what the switches act on", pool.Lamps.Any(l => l.Visible) && mirrors.Panes.Count > 0
                   && cuts.Count > 0 && ghost.Visible && backdrop.Rings.Count == 2 && fog.Visible
                   && VeilUniforms.Materials().Count > 0 && HemiUniforms.Materials().Count > 0 && VeilUniforms.State.Alpha > 0,
                   $"lamps {pool.Lamps.Count(l => l.Visible)} panes {mirrors.Panes.Count} cuts {cuts.Count} ghost {ghost.Visible}");

            string before = Snapshot(ctx, cuts);
            var applied = new List<string>();
            foreach (var v in BenchMatrix.Variants)
            {
                var sw = BenchSwitches.Apply(v.Name, ctx);
                Effect(v.Name, sw, ctx, cuts, camera);
                if (sw.Applied) applied.Add(v.Name);
                sw.Restore();
                fog.Decide();
                string after = Snapshot(ctx, cuts);
                Expect($"M2 {v.Name} restores everything", after == before, $"\nbefore {before}\nafter  {after}");
            }
            return $"matrix M0..M3 ok ({BenchMatrix.Variants.Count} variants, {schedule.Count} passes interleaved, {applied.Count} "
                   + $"switched on the props world: {string.Join(" ", applied)}; fog-pass n/a headless, every restore = the snapshot before)";
        }
        finally
        {
            SubmergedGhost.Off = ghostOff;
            VeilUniforms.Off = false;
            HemiUniforms.Off = false;
            CutMaterials.Plain = false;
            gate?.Detach();
            built?.Models?.FreeAll();
            root.QueueFree();
        }
    }

    /// <summary>Task 40 review regression: an extras pass survives ticks, redrape and new sheets;
    /// restoring it uses the current tier, including a prop culled during the pass.</summary>
    private static async Task WorldPropWaterSwitch(WorldBuilder builder)
    {
        var map = JsonNode.Parse(builder.FirstMap!.Value.GetRawText())!.AsObject();
        var row = map["world_props"]![0]!.AsObject();
        row["water"] = JsonNode.Parse("""{"regions":[{"outline":[[0,0],[2,0],[2,2],[0,2]],"y":1,"tint":"#337799","opacity":0.5}]}""");
        map["world_props_sig"] = "matrix-water";
        var props = builder.WorldProps!;
        props.SyncWorldMap(JsonSerializer.SerializeToElement(map));
        var r = props.Records.Values.Single();
        var near = new Vector3((float)r.Spec.AnchorX, 0, (float)r.Spec.AnchorZ);
        await props.TickAsync(near);
        var sw = BenchSwitches.Apply("no-water-extras", new BenchSwitchContext { Builder = builder });
        try
        {
            await props.TickAsync(near); props.Redrape();
            Expect("M1 world-prop water stays suppressed on tick/redrape", !r.Sheets[0].Visible, "sheet reappeared during extras pass");
            row["water"]!["regions"]![0]!["y"] = 2; map["world_props_sig"] = "matrix-water-new";
            props.SyncWorldMap(JsonSerializer.SerializeToElement(map));
            Expect("M1 newly replaced sheets stay suppressed", !r.Sheets[0].Visible, "new sheet appeared");
            await props.TickAsync(near + new Vector3(1000, 0, 0));
        }
        finally { sw.Restore(); }
        Expect("M2 restore respects current culled tier", !r.Sheets[0].Visible, "restore showed a culled sheet");
        await props.TickAsync(near);
        Expect("M2 restoring extras allows water at visible tier", r.Sheets[0].Visible, "sheet stayed hidden");
        props.SyncWorldMap(builder.FirstMap.Value);
    }

    private static void Effect(string variant, BenchSwitch sw, BenchSwitchContext c, List<CutHandle.Entry> cuts, Camera3D camera)
    {
        var s = c.Stage!;
        var fog = c.Fog!;
        var b = c.Builder!;
        switch (variant)
        {
            case BenchMatrix.Baseline:
                Expect($"M1 {variant} switches nothing", sw.Applied && sw.Detail == "nothing switched", sw.Detail);
                break;
            case "no-shadow":
                Expect("M1 no-shadow", sw.Applied && !s.Sun.ShadowEnabled, "");
                break;
            case "no-hemi-extra-lights":
                Expect("M1 no-hemi-extra-lights: the pair hidden, the terrain term zero, ambient untouched", sw.Applied
                       && !s.HemiUp.Visible && !s.HemiDown.Visible && s.Env.AmbientLightEnergy > 0
                       && HemiUniforms.Materials().All(m => m.GetShaderParameter(HemiUniforms.Uniform).AsVector3() == Vector3.Zero), sw.Detail);
                break;
            case "no-fog-pass":
                Expect("M1 no-fog-pass", sw.Applied && !fog.Visible && !fog.ComputeActive, "");
                break;
            case "no-veil":
                Expect("M1 no-veil: fv_alpha 0 everywhere", sw.Applied
                       && VeilUniforms.Materials().All(m => m.GetShaderParameter("fv_alpha").AsSingle() == 0f), sw.Detail);
                break;
            case "no-backdrop":
                Expect("M1 no-backdrop", sw.Applied && c.Backdrop!()!.Visible == false, "");
                break;
            case "no-water-extras":
                var (_, _, sheets, ghost) = b.WorldPropWater[^1];
                Expect("M1 no-water-extras: ghost and sheet hidden", sw.Applied && SubmergedGhost.Off && !ghost!.Visible
                       && ghost.Parts.All(p => !p.Visible) && !sheets[0].Visible, sw.Detail);
                break;
            case "no-mirrors":
                Expect("M1 no-mirrors: no pass granted", sw.Applied && b.Mirrors!.Suspended && b.Mirrors.Tick(camera) == 0, sw.Detail);
                break;
            case "no-prop-lights":
                Expect("M1 no-prop-lights: the pool hidden (lamps and halos)", sw.Applied && !b.PropLights!.Visible
                       && b.PropLights.Lamps.All(l => !l.IsVisibleInTree()), sw.Detail);
                break;
            case "no-cut-shader":
                Expect("M1 no-cut-shader: every cut surface wears its source", sw.Applied && CutMaterials.Plain
                       && cuts.All(e => e.Mesh.GetSurfaceOverrideMaterial(e.Surface) == e.Source), sw.Detail);
                break;
            case "terrain-lod-coarse":
                Expect("M1 terrain-lod-coarse: pixel scale × 0.5", sw.Applied && b.Terrain!.PixelScaleFactor == 0.5, "");
                break;
            case "shadow-atlas-2048":
                Expect("M1 shadow-atlas-2048 from the project's 4096", sw.Applied && BenchSwitches.AtlasSetting().Size == 4096
                       && sw.Detail.Contains("4096 → 2048"), sw.Detail);
                break;
            case "fog-pass":
                // M3: no RenderingDevice on the dummy renderer — the screen pass fogs anyway, the switch says so.
                Expect("M3 fog-pass headless: n/a, the screen pass fogs the main view", !sw.Applied && fog.PassInMainView
                       && !fog.ComputeActive && fog.Compute is { Available: false }, sw.Detail);
                break;
            case "no-scatter":
                Expect("M1 no-scatter: subtree hidden and suspended", sw.Applied && !c.Scatter!.Visible
                    && c.Scatter.ProcessMode == Node.ProcessModeEnum.Disabled, sw.Detail);
                break;
            case "no-undergrowth":
                Expect("M1 no-undergrowth: authored field stays visible", sw.Applied && !c.Scatter!.Undergrowth.Visible
                    && c.Scatter.Field.Visible && c.Scatter.Undergrowth.ProcessMode == Node.ProcessModeEnum.Disabled, sw.Detail);
                break;
            case "no-impostors":
                Expect("M1 no-impostors: gate persists across bins", sw.Applied && !c.Scatter!.Field.ImpostorsEnabled
                    && c.Scatter.Field.Visible && c.Scatter.Undergrowth.Visible, sw.Detail);
                break;
            case "no-figures":
                // The props world carries no figure manager: the pass runs and says so (the offline world switches 15 figures).
                Expect("M1 no-figures without figures: n/a, said so", !sw.Applied && sw.Detail == "no figure manager", sw.Detail);
                break;
            case "shadow-full-view":
                Expect("M1 shadow-full-view: every caster carries the caster layer", sw.Applied && c.Gate!.Off
                       && c.Gate.Inside > 0, sw.Detail);
                break;
            default:
                throw new InvalidOperationException($"matrix check: no expectation for variant '{variant}'");
        }
    }

    /// <summary>Everything a switch may touch, as one string (equal before a switch and after its restore).</summary>
    private static string Snapshot(BenchSwitchContext c, List<CutHandle.Entry> cuts)
    {
        var s = c.Stage!;
        var b = c.Builder!;
        var fog = c.Fog!;
        var (_, _, sheets, ghost) = b.WorldPropWater[^1];
        var wet = b.Terrain?.Materials.Wet;
        return string.Join(" | ", new object?[]
        {
            s.Sun.ShadowEnabled, s.HemiUp.Visible, s.HemiDown.Visible, HemiUniforms.Off,
            string.Join(",", HemiUniforms.Materials().Select(m => m.GetShaderParameter(HemiUniforms.Uniform).AsVector3())),
            fog.Visible, fog.Off, fog.UseCompute, fog.ComputeActive, fog.PassInMainView, VeilUniforms.Off,
            c.Gate!.Off, c.Gate.Inside,
            string.Join(",", VeilUniforms.Materials().Select(m => m.GetShaderParameter("fv_alpha").AsSingle())),
            c.Backdrop!()!.Visible, wet?.GetShaderParameter("tw_ripple_on").ToString(), SubmergedGhost.Off, ghost!.Visible,
            string.Join(",", ghost.Parts.Select(p => p.Visible)), sheets[0].Visible, b.Waterfalls?.Visible,
            b.Mirrors!.Suspended, b.PropLights!.Visible, CutMaterials.Plain,
            string.Join(",", cuts.Select(e => e.Mesh.GetSurfaceOverrideMaterial(e.Surface)?.GetInstanceId())),
            b.Terrain!.PixelScaleFactor,
            c.Scatter!.Visible, c.Scatter.ProcessMode, c.Scatter.Undergrowth.Visible,
            c.Scatter.Undergrowth.ProcessMode, c.Scatter.Field.ImpostorsEnabled,
        }.Select(o => o?.ToString() ?? "null"));
    }

    private static bool IsInstanceValid(GodotObject? o) => o is not null && GodotObject.IsInstanceValid(o);

    private static void Expect(string what, bool ok, string detail)
    {
        if (!ok) throw new InvalidOperationException($"{what}: {detail}");
    }
}
