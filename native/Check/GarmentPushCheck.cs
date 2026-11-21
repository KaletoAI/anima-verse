using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Json;
using AnimaNative.Figures;
using AnimaNative.Gltf;
using AnimaNative.Overview;
using AnimaNative.Scene;
using AnimaNative.World;
using Godot;

namespace AnimaNative.Check;

/// <summary>
/// The GPU garment push part of <c>--check secondary</c> (<see cref="GarmentPushModifier"/>, garmentCollision.ts), on a
/// GLB built here and imported by Godot like every model: a rig, a body mesh, card hair (<c>garment_hair_long</c>:
/// alpha MASK 0.15, double-sided, vertex colours, a <c>_COLLIDE</c> weight per vertex), a shirt
/// (<c>garment_top_shirt</c>, opaque) and boots (<c>garment_footwear_boots</c>), all on one skin.
///
///   G1 off: <c>--garment-push</c> not given — no modifier; every mesh and every surface override of the figure is the
///      very object it was before the body was set (reference-equal).
///   G2 on: the hair and the shirt are pushed, the boots and the body are not; hair 4 capsules (torso, arm, head,
///      chest_hair), shirt 2 (torso, head), ≤ COLLIDE_MAX; the mesh copy carries CUSTOM0 = the vertex position and the
///      GLB's <c>_COLLIDE</c> of THAT vertex (matched by position, Godot's order), 1 on the shirt; the copy is cached per
///      template mesh.
///   G3 the look: every push material is the source's shader text plus the push, nothing else (removing the inserted
///      block and call gives the generated text back), compiles (<see cref="ShaderSafety"/>), keeps every uniform of the
///      unpushed shader and every value the room-cut port feeds it (compared one by one); the hair keeps
///      alpha_scissor_threshold 0.15, cull_disabled and the vertex-colour albedo. A broken shader fails the gate.
///   G4 the space: figure scaled 1.3, turned 40° and moved; Spine2 and Head posed. The uniform ends equal (≤ 1e-4 m)
///      the skinning Godot applies to the capsule's bind ends (bone global pose · bind pose · bind end), i.e. VERTEX's
///      space; meshGlobal · uniform equals the CPU twin's world capsule (the binding the hair chains use), the radius
///      scales with the figure; the bind uniforms are the bind capsules. A new pose changes the uniforms, not the bind.
///   G5 the twin and the strands: a skinned-normal twin installed over a pushed surface is wrapped again on the next
///      frame (its code + the push, its skin parameter copied), <see cref="GarmentPushModifier.Unwrap"/> sees through
///      it; Exclude(hair) puts the hair's own overrides back and stops its uniform writes, Exclude off restores the push.
///   G6 shadows: no shadow mesh on the copy and the casting setting untouched — Godot draws the shadow pass with the
///      surface material's own vertex(), the push included (no second material to keep in step).
///   G7 release: the original meshes and overrides come back.
/// </summary>
public static class GarmentPushCheck
{
    private sealed record Joint(string Name, int Parent, double X, double Y, double Z);

    private static readonly Joint[] Rig =
    {
        new("mixamorig:Hips", -1, 0, 0, 0), new("mixamorig:Spine2", 0, 0, 1.3, 0), new("mixamorig:Head", 1, 0, 0.3, 0),
        new("mixamorig:LeftArm", 1, 0.2, 0.1, 0), new("mixamorig:LeftFoot", 0, 0.1, 0.05, 0),
    };
    private const int Spine2 = 1, Head = 2, LeftArm = 3, LeftFoot = 4;

    private static readonly string Payload = "{\"version\":" + Collision.Version + ",\"capsules\":["
        + "{\"id\":\"head\",\"a\":\"mixamorig:Head\",\"b\":\"mixamorig:Head\",\"r\":0.09,\"region\":\"head\",\"a_pos\":[0,1.62,0],\"b_pos\":[0,1.72,0]},"
        + "{\"id\":\"chest\",\"a\":\"mixamorig:Spine2\",\"b\":\"mixamorig:Spine2\",\"r\":0.12,\"region\":\"torso\",\"a_pos\":[0,1.1,0],\"b_pos\":[0,1.45,0]},"
        + "{\"id\":\"l_arm\",\"a\":\"mixamorig:LeftArm\",\"b\":\"mixamorig:LeftArm\",\"r\":0.05,\"region\":\"arm\",\"a_pos\":[0.2,1.4,0],\"b_pos\":[0.5,1.4,0]},"
        + "{\"id\":\"chest_h\",\"a\":\"mixamorig:Spine2\",\"b\":\"mixamorig:Head\",\"r\":0.1,\"region\":\"chest_hair\"},"
        + "{\"id\":\"outer\",\"a\":\"mixamorig:Spine2\",\"b\":\"mixamorig:Spine2\",\"r\":0.2,\"region\":\"outer_trunk\"}]}";

    public static string Run(Node3D world)
    {
        var glb = GlbLoader.Prepare(BuildGlb(out var hairPos, out var hairWeight));
        var collision = CollisionPayload.Parse(JsonDocument.Parse(Payload).RootElement)!;
        var weights = StrandGlb.Read(glb, GarmentPushModifier.WeightAttribute);
        bool was = GarmentPushModifier.Enabled;
        try
        {
            // ---- G1 off ----
            GarmentPushModifier.Enabled = false;
            var (offFig, offRoot, _, before) = Make(world, glb, "PushOff", collision, weights);
            var after = Snapshot(offRoot);
            Expect("G1 off: no modifier", offFig.GarmentPush is null, "");
            Expect("G1 off: every mesh and override is the same object", Same(before, after), "");
            offFig.Free();

            // ---- G2 on ----
            GarmentPushModifier.Enabled = true;
            var (fig, root, skel, orig) = Make(world, glb, "PushOn", collision, weights);
            var push = fig.GarmentPush ?? throw new InvalidOperationException("garment push: G2 built nothing (" + string.Join("; ", Skipped(root)) + ")");
            var hair = push.Entries.SingleOrDefault(e => e.Mesh.Name == "garment_hair_long");
            var top = push.Entries.SingleOrDefault(e => e.Mesh.Name == "garment_top_shirt");
            Expect("G2 hair and shirt pushed", hair is not null && top is not null && push.Entries.Count == 2,
                   string.Join(",", push.Entries.Select(e => $"{e.Mesh.Name}:{e.Kind}")) + " skipped " + string.Join("; ", push.Skipped));
            var untouched = Snapshot(root).Where(s => s.Node.Name == "body" || s.Node.Name == "garment_footwear_boots").ToList();
            Expect("G2 body and boots untouched", untouched.Count == 2 && untouched.All(s => orig.Any(o => o.Node == s.Node && o.Mesh == s.Mesh
                       && o.Overrides.SequenceEqual(s.Overrides))), string.Join(",", Snapshot(root).Select(s => s.Node.Name)));
            Expect("G2 hair capsules torso, arm, head, chest_hair", string.Join(",", hair!.Capsules.Select(c => c.Capsule.Id)) == "head,chest,l_arm,chest_h",
                   string.Join(",", hair.Capsules.Select(c => c.Capsule.Id)));
            Expect("G2 shirt capsules torso, head", string.Join(",", top!.Capsules.Select(c => c.Capsule.Id)) == "head,chest",
                   string.Join(",", top.Capsules.Select(c => c.Capsule.Id)));
            Expect("G2 ≤ COLLIDE_MAX", push.Entries.All(e => e.Local.Length <= Collision.CollideMax && e.Local.Length == e.Capsules.Count), "");
            Expect("G2 the figure wears the copy", hair.Mesh.Mesh == hair.PushMesh && top.Mesh.Mesh == top.PushMesh && hair.PushMesh != hair.Original, "");
            Expect("G2 the copy is cached per template mesh",
                   GarmentPushModifier.PushMeshOf((ArrayMesh)hair.Original, weights, out _) == hair.PushMesh, "");
            CheckCustom0("G2 hair", hair, (p, i) => Weight(hairPos, hairWeight, p));
            CheckCustom0("G2 shirt", top, (_, _) => 1.0);
            int weighted = Enumerable.Range(0, hairPos.Length / 3).Count(i => hairWeight[i] != 1);
            Expect("G2 the hair has weights other than 1", weighted >= 3, $"{weighted}");

            // ---- G3 the look ----
            int compared = 0;
            foreach (var e in push.Entries)
                foreach (var (index, mat) in e.SurfaceIndices.Zip(e.Materials))
                    compared += Look($"G3 {e.Mesh.Name}/{index}", e, index, mat);
            var hairMat = hair.Materials.Single();
            var hairSrc = (BaseMaterial3D)((ArrayMesh)hair.Original).SurfaceGetMaterial(0);
            Expect("G3 the hair source is card hair", hairSrc.Transparency == BaseMaterial3D.TransparencyEnum.AlphaScissor
                   && Math.Abs(hairSrc.AlphaScissorThreshold - 0.15) < 1e-6 && hairSrc.CullMode == BaseMaterial3D.CullModeEnum.Disabled
                   && hairSrc.VertexColorUseAsAlbedo, $"{hairSrc.Transparency} {hairSrc.AlphaScissorThreshold} {hairSrc.CullMode} {hairSrc.VertexColorUseAsAlbedo}");
            Expect("G3 hair keeps scissor 0.15, double sides, vertex colour",
                   Math.Abs(hairMat.GetShaderParameter("alpha_scissor_threshold").AsSingle() - 0.15f) < 1e-6
                   && hairMat.Shader.Code.Contains("cull_disabled") && hairMat.Shader.Code.Contains("ALPHA_SCISSOR_THRESHOLD")
                   && hairMat.Shader.Code.Contains("albedo_tex *= COLOR"), "");
            Expect("G3 hair squeezes, the shirt does not", hairMat.Shader.Code.Contains("sr[ COLLIDE_MAX ]")
                   && !top.Materials.Single().Shader.Code.Contains("sr[ COLLIDE_MAX ]"), "");
            var broken = new Shader { Code = GarmentPush.Inject("shader_type spatial;\nvoid vertex() {\n}\n", false).Replace("float r = collideA[ i ].w;", "float r = collideA[ i ];") };
            Expect("G3 the gate refuses a broken push", !ShaderSafety.Ok(broken, "garment-push[check-broken]"), "");

            // ---- G4 the space ----
            fig.Transform = new Transform3D(new Basis(Vector3.Up, Mathf.DegToRad(40)).Scaled(Vector3.One * 1.3f), new Vector3(3, 0.5f, -2));
            skel.SetBonePoseRotation(Spine2, new Quaternion(Vector3.Back, Mathf.DegToRad(30)));
            skel.SetBonePoseRotation(Head, new Quaternion(Vector3.Right, Mathf.DegToRad(20)));
            push.UpdateNow();
            double space = Space(push, hair, skel), worldErr = WorldTwin(push, hair, skel, fig);
            double bindErr = BindUniforms(hair);
            var aBefore = hair.Materials.Single().GetShaderParameter("collideA").AsVector4Array();
            var bindBefore = hair.Materials.Single().GetShaderParameter("collideBindA").AsVector4Array();
            skel.SetBonePoseRotation(Head, new Quaternion(Vector3.Right, Mathf.DegToRad(-25)));
            int updates = push.Updates;
            push.UpdateNow();
            var aAfter = hair.Materials.Single().GetShaderParameter("collideA").AsVector4Array();
            var bindAfter = hair.Materials.Single().GetShaderParameter("collideBindA").AsVector4Array();
            Expect("G4 a new pose moves the head capsule", aBefore[0].DistanceTo(aAfter[0]) > 0.01 && push.Updates == updates + 2,
                   $"{aBefore[0]} → {aAfter[0]}");
            Expect("G4 the bind uniforms stay", bindBefore.SequenceEqual(bindAfter), "");
            double space2 = Space(push, hair, skel);

            // ---- G5 the twin and the strands ----
            var topSrc = (BaseMaterial3D)((ArrayMesh)top.Original).SurfaceGetMaterial(0);
            var twin = SkinNormalMaterial.TryConvert(topSrc) ?? throw new InvalidOperationException("garment push: no normal twin for the shirt");
            top.Mesh.SetSurfaceOverrideMaterial(0, twin);
            push.UpdateNow();
            var wrapped = top.Mesh.GetSurfaceOverrideMaterial(0) as ShaderMaterial;
            Expect("G5 the twin is wrapped again", wrapped is not null && wrapped != twin && GarmentPushModifier.Unwrap(wrapped) == twin
                   && wrapped.Shader.Code.Contains(GarmentPush.Marker) && wrapped.Shader.Code.Contains(SkinNormalMaterial.SkinParam), "");
            compared += Look("G5 shirt twin", top, 0, wrapped!);
            var hairOwn = hair.Mesh.GetSurfaceOverrideMaterial(0);
            push.Exclude(hair.Mesh, true);
            int excludedUpdates = push.Updates;
            push.UpdateNow();
            Expect("G5 excluded: the hair wears its own material, no uniform writes",
                   hair.Mesh.GetSurfaceOverrideMaterial(0) is null && push.Updates == excludedUpdates + 1, "");
            push.Exclude(hair.Mesh, false);
            Expect("G5 back: the push again", hair.Mesh.GetSurfaceOverrideMaterial(0) == hairOwn, "");

            // ---- G6 shadows ----
            Expect("G6 one material draws and casts", push.Entries.All(e => e.PushMesh.ShadowMesh is null
                   && e.Mesh.CastShadow == GeometryInstance3D.ShadowCastingSetting.On), "");

            // ---- G7 release ----
            push.Release();
            // The shirt's override is the twin installed in G5 (what the secondary motion would own), the rest as imported.
            var released = Snapshot(root).Where(s => orig.Any(o => o.Node == s.Node)).ToList();
            var expected = orig.Select(o => o.Node == top.Mesh ? (o.Node, o.Mesh, new Material?[] { twin }) : o).ToList();
            Expect("G7 release restores", Same(expected, released) && push.IsQueuedForDeletion(), "");
            fig.Free();
            return $"; garment push G1..G7 ok (off = same objects; {compared} uniforms compared; space {Math.Max(space, space2):0.0e0} m, "
                   + $"world twin {worldErr:0.0e0} m, bind {bindErr:0.0e0} m; {weighted} weighted hair vertices)";
        }
        finally
        {
            GarmentPushModifier.Enabled = was;
        }
    }

    // ---- G2 / G3 -----------------------------------------------------------------------------------------------------

    private static void CheckCustom0(string label, GarmentPushModifier.Entry e, Func<Vector3, int, double> weight)
    {
        var fmt = e.PushMesh.SurfaceGetFormat(0);
        long customType = ((long)fmt >> (int)Mesh.ArrayFormat.FormatCustom0Shift) & (long)Mesh.ArrayFormat.FormatCustomMask;
        Expect(label + " CUSTOM0 is RGBA float", (fmt & Mesh.ArrayFormat.FormatCustom0) != 0 && customType == (long)Mesh.ArrayCustomFormat.RgbaFloat,
               $"{fmt}");
        var arrays = e.PushMesh.SurfaceGetArrays(0);
        var pos = arrays[(int)Mesh.ArrayType.Vertex].AsVector3Array();
        var custom = arrays[(int)Mesh.ArrayType.Custom0].AsFloat32Array();
        var origPos = ((ArrayMesh)e.Original).SurfaceGetArrays(0)[(int)Mesh.ArrayType.Vertex].AsVector3Array();
        bool ok = custom.Length == 4 * pos.Length && pos.SequenceEqual(origPos);
        for (int v = 0; ok && v < pos.Length; v++)
            ok = custom[4 * v] == pos[v].X && custom[4 * v + 1] == pos[v].Y && custom[4 * v + 2] == pos[v].Z
                 && Math.Abs(custom[4 * v + 3] - weight(pos[v], v)) < 1e-6;
        Expect(label + " CUSTOM0 = position, weight", ok, $"{pos.Length} vertices");
    }

    private static double Weight(float[] pos, float[] weight, Vector3 p)
    {
        for (int i = 0; i < weight.Length; i++)
            if (pos[3 * i] == p.X && pos[3 * i + 1] == p.Y && pos[3 * i + 2] == p.Z) return weight[i];
        throw new InvalidOperationException($"garment push: no GLB vertex at {p}");
    }

    /// <summary>The push material against the unpushed one built the same way: text, compile, every uniform and value.</summary>
    private static int Look(string label, GarmentPushModifier.Entry e, int surface, ShaderMaterial mat)
    {
        var source = GarmentPushModifier.Unwrap(mat)!;
        string baseCode;
        var reference = new ShaderMaterial();
        if (source is StandardMaterial3D std)
        {
            var spec = CutMaterials.SpecOf(std);
            baseCode = StandardShaderCode.Generate(spec)!;
            reference.Shader = new Shader { Code = baseCode };
            CutMaterials.FeedStandard(reference, std, spec);
        }
        else
        {
            var sm = (ShaderMaterial)source;
            baseCode = sm.Shader.Code;
            reference = sm;
        }
        string code = mat.Shader.Code, block = GarmentPush.Block(e.Squeeze);
        string back = code.Replace(block, "").Replace(GarmentPush.Apply, "");
        Expect(label + " the source text plus the push only", code.Contains(block) && code.Contains(GarmentPush.Apply) && back == baseCode, "");
        Expect(label + " compiles", ShaderSafety.Ok(mat.Shader, "garment-push[check]"), "");
        var pushed = mat.Shader.GetShaderUniformList().Select(u => u.AsGodotDictionary()["name"].AsString()).ToHashSet();
        var names = reference.Shader.GetShaderUniformList().Select(u => u.AsGodotDictionary()["name"].AsString()).ToList();
        Expect(label + " keeps every uniform", names.Count > 0 && names.All(pushed.Contains)
               && pushed.Except(names).OrderBy(n => n).SequenceEqual(new[] { "collideA", "collideB", "collideBindA", "collideBindB", "collideCount" }.OrderBy(n => n)),
               string.Join(",", names.Where(n => !pushed.Contains(n))));
        foreach (var n in names)
        {
            var want = reference.GetShaderParameter(n);
            var got = mat.GetShaderParameter(n);
            Expect($"{label} {n} copied", want.VariantType == got.VariantType && want.ToString() == got.ToString()
                   && (want.VariantType != Variant.Type.Object || want.AsGodotObject() == got.AsGodotObject()), $"{want} vs {got}");
        }
        Expect(label + " render priority and next pass", mat.RenderPriority == source.RenderPriority && mat.NextPass == source.NextPass, "");
        return names.Count;
    }

    // ---- G4 ------------------------------------------------------------------------------------------------------------

    /// <summary>The uniform ends against Godot's own skinning of the bind ends (bone global pose · bind pose · bind end).</summary>
    private static double Space(GarmentPushModifier push, GarmentPushModifier.Entry e, Skeleton3D skel)
    {
        var skin = e.Mesh.Skin;
        Transform3D SkinOf(string bone)
        {
            int b = skel.FindBone(bone);
            for (int i = 0; i < skin.GetBindCount(); i++)
                if ((skin.GetBindName(i).ToString() is { Length: > 0 } n ? skel.FindBone(n) : skin.GetBindBone(i)) == b)
                    return skel.GetBoneGlobalPose(b) * skin.GetBindPose(i);
            throw new InvalidOperationException($"garment push: {bone} not bound");
        }
        var a = e.Materials.First().GetShaderParameter("collideA").AsVector4Array();
        var bb = e.Materials.First().GetShaderParameter("collideB").AsVector4Array();
        double worst = 0;
        for (int i = 0; i < e.Capsules.Count; i++)
        {
            var c = e.Capsules[i];
            var wantA = SkinOf(skel.GetBoneName(c.Ja.Node)) * V(c.Bind.A);
            var wantB = SkinOf(skel.GetBoneName(c.Jb.Node)) * V(c.Bind.B);
            worst = Math.Max(worst, Math.Max(new Vector3(a[i].X, a[i].Y, a[i].Z).DistanceTo(wantA), new Vector3(bb[i].X, bb[i].Y, bb[i].Z).DistanceTo(wantB)));
            Expect($"G4 radius {c.Capsule.Id} in VERTEX's space", Math.Abs(a[i].W - c.Bind.R) < 1e-6, $"{a[i].W} vs {c.Bind.R}");
        }
        Expect("G4 uniform ends = Godot's skinning of the bind ends", worst < 1e-4, $"{worst:0.0e0} m");
        int count = e.Materials.First().GetShaderParameter("collideCount").AsInt32();
        Expect("G4 collideCount", count == e.Capsules.Count, $"{count}");
        return worst;
    }

    /// <summary>meshGlobal · uniform = the CPU twin's world capsule (<see cref="CollisionBinding"/>, the hair chains' convention).</summary>
    private static double WorldTwin(GarmentPushModifier push, GarmentPushModifier.Entry e, Skeleton3D skel, Figure fig)
    {
        var skelWorld = SecondaryMotionModifier.ToAffine(skel.GlobalTransform);
        var twin = CollisionBinding.Bind(CollisionPayload.Parse(JsonDocument.Parse(Payload).RootElement),
                                         StrandHairModifier.BodyJoints(fig.Body!, skel), Affine.Identity)!;
        twin.Update(n => skelWorld.Times(SecondaryMotionModifier.ToAffine(skel.GetBoneGlobalPose(n))), Affine.Identity, Affine.Identity);
        var meshWorld = e.Mesh.GlobalTransform;
        var a = e.Materials.First().GetShaderParameter("collideA").AsVector4Array();
        double worst = 0;
        for (int i = 0; i < e.Capsules.Count; i++)
        {
            var now = twin.Capsules.Single(c => c.Capsule.Id == e.Capsules[i].Capsule.Id).Now;
            var world = meshWorld * new Vector3(a[i].X, a[i].Y, a[i].Z);
            worst = Math.Max(worst, world.DistanceTo(V(now.A)));
            Expect($"G4 world radius {e.Capsules[i].Capsule.Id}", Math.Abs(a[i].W * 1.3 - now.R) < 1e-5 && Math.Abs(now.R - e.Capsules[i].Capsule.R * 1.3) < 1e-5,
                   $"{a[i].W} · 1.3 vs {now.R}");
        }
        Expect("G4 meshGlobal · uniform = the CPU twin", worst < 1e-4, $"{worst:0.0e0} m");
        return worst;
    }

    private static double BindUniforms(GarmentPushModifier.Entry e)
    {
        var a = e.Materials.First().GetShaderParameter("collideBindA").AsVector4Array();
        var b = e.Materials.First().GetShaderParameter("collideBindB").AsVector4Array();
        double worst = 0;
        for (int i = 0; i < Collision.CollideMax; i++)
        {
            if (i >= e.Capsules.Count) { Expect("G4 unused bind slot off", a[i].W < 0, $"{a[i]}"); continue; }
            var c = e.Capsules[i];
            Expect("G4 bind rule on", a[i].W == 0, $"{a[i]}");
            worst = Math.Max(worst, Math.Max(new Vector3(a[i].X, a[i].Y, a[i].Z).DistanceTo(V(c.Bind.A)), new Vector3(b[i].X, b[i].Y, b[i].Z).DistanceTo(V(c.Bind.B))));
        }
        // The chest capsule's bind ends are its payload a_pos / b_pos (the joints' bind = the skin's bind pose).
        var chest = e.Capsules.Select((c, i) => (c, i)).Single(x => x.c.Capsule.Id == "chest").i;
        Expect("G4 chest bind = a_pos / b_pos", new Vector3(a[chest].X, a[chest].Y, a[chest].Z).DistanceTo(new Vector3(0, 1.1f, 0)) < 1e-6
               && new Vector3(b[chest].X, b[chest].Y, b[chest].Z).DistanceTo(new Vector3(0, 1.45f, 0)) < 1e-6, $"{a[chest]} {b[chest]}");
        Expect("G4 bind uniforms = bind capsules", worst < 1e-6, $"{worst}");
        return worst;
    }

    private static Vector3 V(V3 v) => new((float)v.X, (float)v.Y, (float)v.Z);

    // ---- the figure ----------------------------------------------------------------------------------------------------

    private static List<(MeshInstance3D Node, Mesh? Mesh, Material?[] Overrides)> Snapshot(Node root)
        => Walk(root).OfType<MeshInstance3D>().Select(mi => (Node: mi, Mesh: (Mesh?)mi.Mesh,
               Overrides: Enumerable.Range(0, mi.Mesh?.GetSurfaceCount() ?? 0).Select(s => (Material?)mi.GetSurfaceOverrideMaterial(s)).ToArray())).ToList();

    private static bool Same(List<(MeshInstance3D Node, Mesh? Mesh, Material?[] Overrides)> a, List<(MeshInstance3D Node, Mesh? Mesh, Material?[] Overrides)> b)
        => a.Count == b.Count && a.Zip(b).All(p => p.First.Node == p.Second.Node && p.First.Mesh == p.Second.Mesh
                                                   && p.First.Overrides.SequenceEqual(p.Second.Overrides));

    private static IEnumerable<string> Skipped(Node root) => Walk(root).OfType<MeshInstance3D>().Select(m => m.Name.ToString());

    private static (Figure, Node3D, Skeleton3D, List<(MeshInstance3D Node, Mesh? Mesh, Material?[] Overrides)>) Make(
        Node3D world, byte[] glb, string name, CollisionPayload collision, IReadOnlyList<StrandGlbPrimitive> weights)
    {
        var (root, _) = GlbLoader.Import(glb, name);
        var skel = ClipLibrary.Find<Skeleton3D>(root) ?? throw new InvalidOperationException($"garment push: {name} has no skeleton");
        var fig = new Figure(name) { SecondaryManual = true, Collision = collision, Procedural = false, CollidePrimitives = weights };
        world.AddChild(fig);
        fig.SetYaw(0);
        var before = Snapshot(root);
        var body = new Node3D { Name = "Body" };
        body.AddChild(root);
        fig.SetBody(body, true, skel, null);
        if (fig.GarmentPush is { } p) p.Manual = true;
        return (fig, root, skel, before);
    }

    // ---- the GLB -------------------------------------------------------------------------------------------------------

    /// <summary>The rig, a body, card hair with <c>_COLLIDE</c>, a shirt and boots on one skin; inverse binds = the joints'
    /// inverse world translations. <paramref name="hairPos"/>/<paramref name="hairWeight"/>: the hair in GLB order.</summary>
    private static byte[] BuildGlb(out float[] hairPos, out float[] hairWeight)
    {
        var world = new (double X, double Y, double Z)[Rig.Length];
        for (int i = 0; i < Rig.Length; i++)
        {
            var j = Rig[i];
            var p = j.Parent >= 0 ? world[j.Parent] : (0, 0, 0);
            world[i] = (p.X + j.X, p.Y + j.Y, p.Z + j.Z);
        }
        var bin = new MemoryStream();
        var views = new List<string>(); var accessors = new List<string>();
        static string F(double v) => v.ToString("R", System.Globalization.CultureInfo.InvariantCulture);
        int Add(byte[] data, int componentType, string type, int count, string extra = "")
        {
            while (bin.Length % 4 != 0) bin.WriteByte(0);
            views.Add($"{{\"buffer\":0,\"byteOffset\":{bin.Length},\"byteLength\":{data.Length}}}");
            bin.Write(data);
            accessors.Add($"{{\"bufferView\":{views.Count - 1},\"componentType\":{componentType},\"count\":{count},\"type\":\"{type}\"{extra}}}");
            return accessors.Count - 1;
        }
        static byte[] Bytes<T>(T[] a) where T : struct => System.Runtime.InteropServices.MemoryMarshal.AsBytes(a.AsSpan()).ToArray();
        string MinMax(float[] p)
        {
            var mn = Enumerable.Range(0, 3).Select(a => Enumerable.Range(0, p.Length / 3).Min(v => p[3 * v + a]));
            var mx = Enumerable.Range(0, 3).Select(a => Enumerable.Range(0, p.Length / 3).Max(v => p[3 * v + a]));
            return $",\"min\":[{string.Join(",", mn.Select(x => F(x)))}],\"max\":[{string.Join(",", mx.Select(x => F(x)))}]";
        }
        string Prim(float[] pos, int joint, int material, string extra = "", int? extraAccessor = null)
        {
            int nv = pos.Length / 3;
            var nrm = Enumerable.Range(0, nv).SelectMany(_ => new[] { 0f, 0, 1 }).ToArray();
            var js = Enumerable.Range(0, nv).SelectMany(_ => new[] { (ushort)joint, (ushort)0, (ushort)0, (ushort)0 }).ToArray();
            var ws = Enumerable.Range(0, nv).SelectMany(_ => new[] { 1f, 0, 0, 0 }).ToArray();
            var idx = Enumerable.Range(0, nv / 3 * 3).Select(i => (ushort)i).ToArray();
            int aP = Add(Bytes(pos), 5126, "VEC3", nv, MinMax(pos)), aN = Add(Bytes(nrm), 5126, "VEC3", nv);
            int aJ = Add(Bytes(js), 5123, "VEC4", nv), aW = Add(Bytes(ws), 5126, "VEC4", nv), aI = Add(Bytes(idx), 5123, "SCALAR", idx.Length);
            return $"{{\"attributes\":{{\"POSITION\":{aP},\"NORMAL\":{aN},\"JOINTS_0\":{aJ},\"WEIGHTS_0\":{aW}{extra}}},\"indices\":{aI},\"material\":{material}}}";
        }
        // card hair: two triangles of distinct vertices over the shoulders, a weight per vertex
        hairPos = new float[] { -0.15f, 1.5f, 0.05f, 0.15f, 1.5f, 0.05f, 0, 1.75f, 0.05f, -0.15f, 1.5f, -0.05f, 0, 1.75f, -0.06f, 0.16f, 1.48f, -0.05f };
        hairWeight = new float[] { 1f, 0.25f, 0.5f, 0f, 0.75f, 1f };
        var colours = Enumerable.Range(0, 6).SelectMany(i => new[] { 0.3f + 0.1f * i, 0.2f, 0.1f, 1f }).ToArray();
        int aCol = Add(Bytes(colours), 5126, "VEC4", 6), aColl = Add(Bytes(hairWeight), 5126, "SCALAR", 6);
        string hair = Prim(hairPos, Head, 0, $",\"COLOR_0\":{aCol},\"_COLLIDE\":{aColl}");
        string body = Prim(new float[] { -0.01f, 1.3f, 0, 0.01f, 1.3f, 0, 0, 1.3f, 0.01f }, Spine2, 1);
        string shirt = Prim(new float[] { -0.13f, 1.2f, 0.02f, 0.13f, 1.2f, 0.02f, 0, 1.4f, 0.13f, -0.13f, 1.2f, -0.02f, 0, 1.4f, -0.13f, 0.13f, 1.2f, -0.02f }, Spine2, 1);
        string boots = Prim(new float[] { 0.08f, 0.02f, 0, 0.12f, 0.02f, 0, 0.1f, 0.02f, 0.05f }, LeftFoot, 1);
        var ibm = world.SelectMany(p => new[] { 1f, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, (float)-p.X, (float)-p.Y, (float)-p.Z, 1 }).ToArray();
        int aIbm = Add(Bytes(ibm), 5126, "MAT4", Rig.Length);
        string[] meshNames = { "body", "garment_hair_long", "garment_top_shirt", "garment_footwear_boots" };
        var nodes = Rig.Select((j, i) =>
        {
            var kids = Enumerable.Range(0, Rig.Length).Where(c => Rig[c].Parent == i).ToList();
            return $"{{\"name\":{JsonSerializer.Serialize(j.Name)},\"translation\":[{F(j.X)},{F(j.Y)},{F(j.Z)}]"
                   + (kids.Count > 0 ? $",\"children\":[{string.Join(",", kids)}]" : "") + "}";
        }).Concat(meshNames.Select((n, m) => $"{{\"name\":\"{n}\",\"mesh\":{m},\"skin\":0}}"));
        string json = "{\"asset\":{\"version\":\"2.0\"},\"scene\":0,"
            + $"\"scenes\":[{{\"nodes\":[0,{string.Join(",", Enumerable.Range(Rig.Length, meshNames.Length))}]}}],\"nodes\":[{string.Join(",", nodes)}],"
            + $"\"skins\":[{{\"joints\":[{string.Join(",", Enumerable.Range(0, Rig.Length))}],\"inverseBindMatrices\":{aIbm},\"skeleton\":0}}],"
            + "\"materials\":[{\"name\":\"hair\",\"alphaMode\":\"MASK\",\"alphaCutoff\":0.15,\"doubleSided\":true,"
            + "\"pbrMetallicRoughness\":{\"baseColorFactor\":[0.4,0.3,0.2,1],\"metallicFactor\":0,\"roughnessFactor\":0.8}},"
            + "{\"name\":\"cloth\",\"pbrMetallicRoughness\":{\"baseColorFactor\":[0.2,0.3,0.6,1],\"metallicFactor\":0,\"roughnessFactor\":0.9}}],"
            + $"\"meshes\":[{{\"name\":\"body\",\"primitives\":[{body}]}},{{\"name\":\"hair\",\"primitives\":[{hair}]}},"
            + $"{{\"name\":\"shirt\",\"primitives\":[{shirt}]}},{{\"name\":\"boots\",\"primitives\":[{boots}]}}],"
            + $"\"accessors\":[{string.Join(",", accessors)}],\"bufferViews\":[{string.Join(",", views)}],"
            + $"\"buffers\":[{{\"byteLength\":{bin.Length}}}]}}";
        var text = Encoding.UTF8.GetBytes(json);
        int padded = (text.Length + 3) & ~3;
        var data = bin.ToArray();
        int binPadded = (data.Length + 3) & ~3;
        using var ms = new MemoryStream();
        using var w = new BinaryWriter(ms);
        w.Write(0x46546C67u); w.Write(2u); w.Write((uint)(12 + 8 + padded + 8 + binPadded));
        w.Write((uint)padded); w.Write(0x4E4F534Au); w.Write(text); for (int i = text.Length; i < padded; i++) w.Write((byte)0x20);
        w.Write((uint)binPadded); w.Write(0x004E4942u); w.Write(data); for (int i = data.Length; i < binPadded; i++) w.Write((byte)0);
        w.Flush();
        return ms.ToArray();
    }

    private static IEnumerable<Node> Walk(Node n)
    {
        yield return n;
        foreach (var c in n.GetChildren()) foreach (var d in Walk(c)) yield return d;
    }

    private static void Expect(string what, bool ok, string detail)
    {
        if (!ok) throw new InvalidOperationException($"garment push: {what} failed {detail}".TrimEnd());
    }
}
