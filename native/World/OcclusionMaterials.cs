using System.Collections.Generic;
using AnimaNative.Overview;
using AnimaNative.Scene;
using Godot;

namespace AnimaNative.World;

/// <summary>
/// Task 53 / E7-T8: one global write per camera frame, read by all corridor materials. Owned shell clones use
/// CutMaterials' cached shader conversion; scatter/undergrowth share their existing variant shaders. Overview,
/// missing avatars, teardown and first person neutralize the same strength uniform, so nothing needs restoring.
/// </summary>
public static class OcclusionMaterials
{
    public static OcclusionState State { get; private set; } = Occlusion.Uniforms(default, null, false);

    public static void Update(Vector3 camera, Vector3? avatar, bool embodied, bool firstPerson)
    {
        bool on = embodied && !firstPerson;
        State = Occlusion.Uniforms(new(camera.X, camera.Y, camera.Z),
            on && avatar is { } p ? new Vec3(p.X, p.Y, p.Z) : null, on);
        RenderingServer.GlobalShaderParameterSet("av_occ_a", new Vector3((float)State.A.X, (float)State.A.Y, (float)State.A.Z));
        RenderingServer.GlobalShaderParameterSet("av_occ_b", new Vector3((float)State.B.X, (float)State.B.Y, (float)State.B.Z));
        RenderingServer.GlobalShaderParameterSet("av_occ_radius", (float)State.Radius);
        RenderingServer.GlobalShaderParameterSet("av_occ_strength", (float)State.Strength);
    }

    /// <summary>Patch only an explicitly selected shell, preserving mesh resources and borrowed source materials.</summary>
    public static void Apply(Node3D root)
    {
        var clones = new Dictionary<Material, ShaderMaterial?>();
        var empty = CutShader.Pack(null, null, 0, null);
        void Visit(Node node)
        {
            if (node is MeshInstance3D mi && mi.Mesh is { } mesh)
            {
                for (int i = 0; i < mesh.GetSurfaceCount(); i++)
                {
                    var src = mi.MaterialOverride ?? mi.GetActiveMaterial(i);
                    if (src is null) continue;
                    if (!clones.TryGetValue(src, out var clone))
                        clones[src] = clone = CutMaterials.Convert(src, empty, corridor: true);
                    if (clone is null) continue;
                    if (mi.MaterialOverride is not null) { mi.MaterialOverride = clone; break; }
                    mi.SetSurfaceOverrideMaterial(i, clone);
                }
            }
            foreach (var child in node.GetChildren()) Visit(child);
        }
        Visit(root);
    }
}
