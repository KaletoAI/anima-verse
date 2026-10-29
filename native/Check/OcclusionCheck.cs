using System;
using System.IO;
using System.Linq;
using System.Threading.Tasks;
using AnimaNative.Overview;
using AnimaNative.Scatter;
using AnimaNative.Scene;
using AnimaNative.World;
using Godot;

namespace AnimaNative.Check;

/// <summary>
/// Task 53 / E7-T8: actual embody fixture shell/cut/scatter materials and shared frame state, without GPU readback.
/// Avatar feet (-3,.01,1) → chest (-3,1.21,1); camera (-3,1.21,8) → start Z7.5, d7, strength1.
/// The hall's south wall covers X[-6,2.4], Z4, Y[0,3], so (-3,1.21,4) is ON the segment: hide1.
/// Camera moved to (-3,1.21,-6) leaves that point 3m beyond the chest: hide0. First person, missing avatar,
/// overview and teardown have strength0. A plan hull's gate is 1 closed / 0 with cutouts / 1 closed again.
/// Headless probes prove the shader binding and its CPU arithmetic; pixel dithering still needs a GPU look.
/// </summary>
public static class OcclusionCheck
{
    public static async Task<string> RunAsync(Node3D host, string fixtures)
    {
        var world = new Node3D { Name = "OcclusionWorld" };
        host.AddChild(world);
        var source = new FixtureSource(Path.Combine(fixtures, "embody"), fixtures);
        var builder = new WorldBuilder(source, _ => { }, strict: true);
        int n = 0;
        void Is(string name, bool value) { n++; if (!value) throw new InvalidOperationException("corridor " + name); }
        void Near(string name, double value, double want) => Is($"{name}: {value:R} expected {want:R}", Math.Abs(value-want) < 1e-5);
        bool Patched(Material? material) => material is ShaderMaterial m && m.Shader.Code.Contains(OcclusionShader.Marker);
        try
        {
            await builder.BuildAsync(world, "Fixture Hall");
            var hall = builder.Slots["loc-hall"];
            var point = new Vector3(-3,1.21f,4);
            var wall = hall.FarShell.First(m => m.GetAabb().HasPoint(point));
            Is("fixture wall shell patched", Patched(wall.GetActiveMaterial(0)));
            Is("every far-shell material patched", hall.FarShell.All(m => Patched(m.GetActiveMaterial(0))));
            Is("shell and interior share mesh only", hall.FarShell.All(m => m.GetSurfaceOverrideMaterial(0) is not null
                && m.GetSurfaceOverrideMaterial(0) != m.Mesh.SurfaceGetMaterial(0)));
            var camera = new Vector3(-3,1.21f,8);
            var avatar = new Vector3(-3,.01f,1);
            var sample = new Vec3(point.X,point.Y,point.Z);
            OcclusionMaterials.Update(camera, avatar, true, false);
            Near("wall fades between camera and avatar", Occlusion.Hide(OcclusionMaterials.State, sample), 1);
            Near("start clearance", OcclusionMaterials.State.A.Z, 7.5);
            Near("chest endpoint", OcclusionMaterials.State.B.Y, 1.21);
            Near("neighbour fragments stay whole", Occlusion.Hide(OcclusionMaterials.State, new Vec3(0,1.21,4)), 0);
            Is("Bayer discards centre", Occlusion.Hide(OcclusionMaterials.State, sample) > Occlusion.Threshold(0,3));
            OcclusionMaterials.Update(new(-3,1.21f,-6), avatar, true, false);
            Near("wall returns when camera moves", Occlusion.Hide(OcclusionMaterials.State, sample), 0);
            OcclusionMaterials.Update(camera, avatar, true, true);
            Near("first person fades nothing", OcclusionMaterials.State.Strength, 0);
            OcclusionMaterials.Update(camera, avatar, false, false);
            Near("overview fades nothing", OcclusionMaterials.State.Strength, 0);
            OcclusionMaterials.Update(camera, null, true, false);
            Near("missing avatar fades nothing", OcclusionMaterials.State.Strength, 0);
            Is("interior recipe stays whole", hall.Fade.Interior!.FindChildren("*", "MeshInstance3D", true, false)
                .OfType<MeshInstance3D>().All(m => !Patched(m.GetActiveMaterial(0))));

            var scatter = ScatterShaders.Tuft("#668844", .06, 1);
            var grass = ScatterShaders.Undergrowth(new GradientTexture2D(), "#668844", .06);
            Is("scatter patched after sway", Patched(scatter) && scatter.Shader.Code.Contains("VERTEX.xz += 0.06"));
            Is("undergrowth patched with instance color", Patched(grass) && grass.Shader.Code.Contains("* COLOR"));
            Is("scatter program shared", scatter.Shader == ScatterShaders.Tuft("#ffffff", .06, 2).Shader);
            Is("impostor patched", Patched(ScatterShaders.Impostor(new GradientTexture2D())));
            Is("bake unaffected by live corridor", !Patched(ScatterShaders.ForImpostorBake(null, 1, Vector3.Zero)));

            var borrowed = new StandardMaterial3D();
            var mesh = new BoxMesh { Material = borrowed };
            var hull = new MeshInstance3D { Mesh = mesh };
            world.AddChild(hull);
            var poly = new P2[] { new(-1,-1), new(1,-1), new(1,1), new(-1,1) };
            var handle = CutMaterials.Apply(hull, null, new[] { poly }, null, node => node.Transform, corridor: true)!;
            var clone = handle.Entries.Single().Material;
            Is("plan hull uses cut clone", Patched(clone) && hull.GetActiveMaterial(0) == clone && mesh.Material == borrowed);
            Is("cutout and corridor compose", clone.Shader.Code.Contains("av_cut_discard"));
            Near("closed hull corridor gate", clone.GetShaderParameter("occ_gate").AsDouble(), 1);
            handle.SetCutoutsEnabled(true);
            Near("open hull corridor gate", clone.GetShaderParameter("occ_gate").AsDouble(), 0);
            Near("open hull keeps cutouts", clone.GetShaderParameter("cut_on").AsDouble(), 1);
            handle.SetCutoutsEnabled(false);
            Near("closed hull gate restored", clone.GetShaderParameter("occ_gate").AsDouble(), 1);
            var second = CutMaterials.Apply(new MeshInstance3D { Mesh = mesh }, null, new[] { poly }, null, node => node.Transform, corridor: true)!;
            Is("hulls share shader but own gate", clone.Shader == second.Entries.Single().Material.Shader && clone != second.Entries.Single().Material);
            second.Entries.Single().Mesh.Free();
            Is("corridor compiles", ShaderSafety.Ok(clone.Shader, "corridor-check"));
            Is("grass compiles", ShaderSafety.Ok(grass.Shader, "corridor-grass-check"));
            Is("impostor compiles", ShaderSafety.Ok(ScatterShaders.Impostor(new GradientTexture2D()).Shader, "corridor-impostor-check"));
            hall.Fade.Snap(.5);
            Is("existing roof fade still runs", wall.Transparency > 0);
            OcclusionMaterials.Update(Vector3.Zero, null, false, false);
            Near("teardown clears corridor", OcclusionMaterials.State.Strength, 0);
            return $"corridor cases={n} wall=fade/restore first_person=neutral radius=1.5 bayer=4x4 hull_gate=inverse";
        }
        finally
        {
            OcclusionMaterials.Update(Vector3.Zero, null, false, false);
            builder.StopResidency(); builder.Models?.FreeAll();
            world.QueueFree();
            await host.ToSignal(host.GetTree(), SceneTree.SignalName.ProcessFrame);
            await host.ToSignal(host.GetTree(), SceneTree.SignalName.ProcessFrame);
        }
    }
}
