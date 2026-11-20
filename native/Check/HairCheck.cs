using System;
using System.Collections.Generic;
using System.IO;
using System.Linq;
using System.Text;
using System.Text.Json;
using AnimaNative.Figures;
using AnimaNative.Gltf;
using AnimaNative.Overview;
using Godot;

namespace AnimaNative.Check;

/// <summary>
/// The hair-chain part of <c>--check secondary</c> (the browser's secondaryMotion.ts hair pass: today's skin and the tip
/// contact against the model's <c>collision</c> capsules), on GLBs built here — a skinned hair chain imported by Godot
/// like every model and driven through a real <see cref="Figure"/> with <see cref="Figure.Collision"/> set, so the
/// modifier's own wiring (body joints from the skins, the reach, SetCollision) is what runs. Numbers from the source
/// smokes' hand derivations:
///
///   H1 scripts/smoke_hair_chain_contact.mjs: Hips → mixamorig:Head (0, 1.6, 0) → HairGen_c00_00 (0, 0.1, −0.07) →
///      HairGen_c00_01 (0, −0.1, 0), a head sphere r 0.05 on Head; the head pitches −40° about X over 0.25 s, 90 frames
///      at 60 fps. J1 (the head of _01) starts 0.07 from the sphere's centre; without the capsule it sinks more than
///      5 mm into it, with the capsule never more than 1 mm.
///   H2 scripts/smoke_hair_today_skin.mjs [1]: Hips → Spine2 (0, 1.3, 0) → Head (0, 0.3, 0) → _00 → _01 → _02, a still
///      hair group with anchor_from Head and the rows _00 {Head 1}, _01 {Head .5, Spine2 .5}, _02 {Spine2 1}; Spine2
///      +30°, Head −40° about X: _00 (0, 1.64613, 0.06370), _01 (0, 1.57123, 0.08522), _02 (0, 1.50821, 0.03938).
///   H3 the same smoke's [3]: a rows-only group (no bones, the row _02 {Head .5, Spine2 .5}) builds the motion and puts
///      _02 at (0, 1.47869, 0.06890).
/// </summary>
public static class HairCheck
{
    private const double Tol = 1e-4;

    private sealed record Joint(string Name, int Parent, double X, double Y, double Z);

    private static readonly Joint[] ContactRig =
    {
        new("mixamorig:Hips", -1, 0, 0, 0), new("mixamorig:Head", 0, 0, 1.6, 0),
        new("HairGen_c00_00", 1, 0, 0.1, -0.07), new("HairGen_c00_01", 2, 0, -0.1, 0),
    };
    private static readonly Joint[] TodayRig =
    {
        new("mixamorig:Hips", -1, 0, 0, 0), new("mixamorig:Spine2", 0, 0, 1.3, 0), new("mixamorig:Head", 1, 0, 0.3, 0),
        new("HairGen_c00_00", 2, 0, 0.1, -0.07), new("HairGen_c00_01", 3, 0, -0.1, 0), new("HairGen_c00_02", 4, 0, -0.1, 0),
    };

    private const string Group = "\"freq_hz\":1,\"zeta\":0.5,\"gravity\":0,\"gravity_scale\":1,\"gain\":1,\"max_deg\":35,\"sag_max_deg\":10,"
        + "\"spill_max_deg\":0,\"head_sag\":1,\"axis_gain\":[1,1,1],\"flatten\":0,\"stretch\":0,\"spread\":0.5,\"flatten_floor\":1,"
        + "\"spill\":0,\"translate\":0,\"squash\":[1,1],\"length\":1,\"girth\":1,\"rest_deg\":0,\"rest_max_deg\":90,\"rigid_tail\":0,"
        + "\"scale_axis\":\"centroid\",\"straighten_deg\":0,\"hair\":true";
    /// <summary>The smoke's <c>still</c> group: <see cref="Group"/> with no swing at all (gain and both budgets 0).</summary>
    private static readonly string Still = Group.Replace("\"gain\":1", "\"gain\":0").Replace("\"max_deg\":35", "\"max_deg\":0")
        .Replace("\"sag_max_deg\":10", "\"sag_max_deg\":0") + ",\"anchor_from\":\"mixamorig:Head\"";

    private static MotionPayload Payload(string group)
        => MotionPayload.Parse(JsonDocument.Parse($"{{\"rev\":\"h\",\"groups\":{{\"hair_c00\":{{{group}}}}}}}").RootElement)!;

    public static string Run(Node3D world)
    {
        // ---- H1 the tip contact ----
        var contactGlb = Glb(ContactRig, new (int Joint, double X, double Y, double Z)[] { (2, 0, 1.65, -0.07), (3, 0, 1.55, -0.07) });
        var chain = Payload($"\"bones\":[\"HairGen_c00_00\",\"HairGen_c00_01\"],{Group}");
        var sphere = CollisionPayload.Parse(JsonDocument.Parse("{\"version\":9,\"capsules\":[{\"id\":\"head\",\"a\":\"mixamorig:Head\","
            + "\"b\":\"mixamorig:Head\",\"r\":0.05,\"region\":\"head\"}]}").RootElement);
        double control = Pitch(world, contactGlb, chain, null, "HairControl", out _);
        double contact = Pitch(world, contactGlb, chain, sphere, "HairContact", out int tips);
        Expect("H1 control: J1 sinks more than 5 mm into the head sphere", control > 0.005, $"{control * 1000:0.000} mm");
        Expect("H1 the head capsule binds to both links", tips == 2, $"{tips} links with contacts");
        Expect("H1 hair contact: J1 at most 1 mm inside", contact <= 0.001, $"{contact * 1000:0.000} mm");

        // ---- H2 today's skin follows the payload rows ----
        var todayGlb = Glb(TodayRig, new (int, double, double, double)[] { (3, 0, 1.65, -0.07), (4, 0, 1.55, -0.07), (5, 0, 1.45, -0.07), (4, 0, 1.6, -0.07) });
        var rows = Payload($"\"bones\":[\"HairGen_c00_00\",\"HairGen_c00_01\"],{Still},\"anchor_blend\":{{\"HairGen_c00_00\":{{\"mixamorig:Head\":1}},"
            + "\"HairGen_c00_01\":{\"mixamorig:Head\":0.5,\"mixamorig:Spine2\":0.5},\"HairGen_c00_02\":{\"mixamorig:Spine2\":1}}");
        var (fig, mod, skel) = Make(world, todayGlb, "HairToday", rows, null);
        Pose(fig, mod, skel, 30, -40);
        NearV("H2 _00 under Head", mod.Rig.World[skel.FindBone("HairGen_c00_00")].Position(), 0, 1.64613, 0.06370);
        NearV("H2 _01 half Head, half Spine2", mod.Rig.World[skel.FindBone("HairGen_c00_01")].Position(), 0, 1.57123, 0.08522);
        NearV("H2 _02 under Spine2", mod.Rig.World[skel.FindBone("HairGen_c00_02")].Position(), 0, 1.50821, 0.03938);
        Expect("H2 the hair bones are owned", mod.Motion.HairCount == 3, $"{mod.Motion.HairCount}");
        fig.Free();

        // ---- H3 a rows-only group ----
        var only = Payload($"\"bones\":[],{Still},\"anchor_blend\":{{\"HairGen_c00_02\":{{\"mixamorig:Head\":0.5,\"mixamorig:Spine2\":0.5}}}}");
        (fig, mod, skel) = Make(world, todayGlb, "HairRows", only, null);
        Pose(fig, mod, skel, 30, -40);
        NearV("H3 rows-only _02", mod.Rig.World[skel.FindBone("HairGen_c00_02")].Position(), 0, 1.47869, 0.06890);
        fig.Free();

        return $"hair H1..H3 ok (J1 depth {control * 1000:0.00} mm → {contact * 1000:0.00} mm with the head capsule; today's skin rows ok)";
    }

    /// <summary>The head pitch of H1; the deepest J1 got into the head sphere (metres, &lt; 0 = never inside).</summary>
    private static double Pitch(Node3D world, byte[] glb, MotionPayload payload, CollisionPayload? collision, string name, out int tips)
    {
        var (fig, mod, skel) = Make(world, glb, name, payload, collision);
        int head = skel.FindBone("mixamorig_Head"), j1 = skel.FindBone("HairGen_c00_01");
        double deepest = double.NegativeInfinity;
        for (int k = 1; k <= 90; k++)
        {
            double angle = -Math.Min(1, k / 60.0 / 0.25) * 40 * Math.PI / 180;
            fig.UpdateFigure(1.0 / 60);
            skel.SetBonePoseRotation(head, new Quaternion(Vector3.Right, (float)angle));
            mod.StepNow(1.0 / 60);
            var w = mod.Rig.World;
            deepest = Math.Max(deepest, 0.05 - w[j1].Position().DistanceTo(w[head].Position()));
        }
        tips = mod.Motion.ContactTips().Count();
        fig.Free();
        return deepest;
    }

    /// <summary>One frame with Spine2 and Head turned about X (degrees).</summary>
    private static void Pose(Figure fig, SecondaryMotionModifier mod, Skeleton3D skel, double spine2, double head)
    {
        fig.UpdateFigure(1.0 / 60);
        skel.SetBonePoseRotation(skel.FindBone("mixamorig_Spine2"), new Quaternion(Vector3.Right, (float)(spine2 * Math.PI / 180)));
        skel.SetBonePoseRotation(skel.FindBone("mixamorig_Head"), new Quaternion(Vector3.Right, (float)(head * Math.PI / 180)));
        mod.StepNow(1.0 / 60);
    }

    private static (Figure, SecondaryMotionModifier, Skeleton3D) Make(Node3D world, byte[] glb, string name, MotionPayload payload,
                                                                       CollisionPayload? collision)
    {
        var (root, _) = GlbLoader.Import(GlbLoader.Prepare(glb), name);
        var skel = ClipLibrary.Find<Skeleton3D>(root) ?? throw new InvalidOperationException($"hair: {name} has no skeleton");
        var fig = new Figure(name) { SecondaryManual = true, Motion = payload, Collision = collision, Procedural = false };
        world.AddChild(fig);
        fig.SetYaw(0);
        var body = new Node3D { Name = "Body" };
        body.AddChild(root);
        fig.SetBody(body, true, skel, null);
        var mod = fig.Secondary ?? throw new InvalidOperationException($"hair: {name} built no motion");
        return (fig, mod, skel);
    }

    /// <summary>
    /// A GLB of a joint tree (translations only) and one skinned mesh: per point a tiny triangle (±1 mm in x, +1 mm in
    /// z) fully weighted to its joint; the inverse bind matrices are the joints' inverse world translations.
    /// </summary>
    private static byte[] Glb(Joint[] joints, (int Joint, double X, double Y, double Z)[] points)
    {
        const float d = 0.001f;
        var pos = new List<float>();
        var idx = new List<ushort>();
        var wts = new List<float>();
        foreach (var p in points)
            foreach (var (ox, oz) in new[] { (d, 0f), (-d, 0f), (0f, d) })
            {
                pos.AddRange(new[] { (float)p.X + ox, (float)p.Y, (float)p.Z + oz });
                idx.AddRange(new ushort[] { (ushort)p.Joint, 0, 0, 0 });
                wts.AddRange(new[] { 1f, 0, 0, 0 });
            }
        var world = new (double X, double Y, double Z)[joints.Length];
        for (int i = 0; i < joints.Length; i++)
        {
            var j = joints[i];
            var parent = j.Parent >= 0 ? world[j.Parent] : (0, 0, 0);
            world[i] = (parent.X + j.X, parent.Y + j.Y, parent.Z + j.Z);
        }
        var ibm = new List<float>();
        foreach (var w in world) ibm.AddRange(new[] { 1f, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, (float)-w.X, (float)-w.Y, (float)-w.Z, 1 });
        int n = pos.Count / 3;
        using var bin = new MemoryStream();
        using (var bw = new BinaryWriter(bin, Encoding.UTF8, true))
        {
            foreach (var f in pos) bw.Write(f);
            foreach (var s in idx) bw.Write(s);
            foreach (var f in wts) bw.Write(f);
            foreach (var f in ibm) bw.Write(f);
        }
        int posLen = n * 12, idxLen = n * 8, wLen = n * 16, ibmLen = joints.Length * 64;
        static string F(double v) => v.ToString("R", System.Globalization.CultureInfo.InvariantCulture);
        var min = Enumerable.Range(0, 3).Select(a => Enumerable.Range(0, n).Min(v => pos[v * 3 + a])).ToArray();
        var max = Enumerable.Range(0, 3).Select(a => Enumerable.Range(0, n).Max(v => pos[v * 3 + a])).ToArray();
        var nodes = joints.Select((j, i) =>
        {
            var kids = Enumerable.Range(0, joints.Length).Where(c => joints[c].Parent == i).ToList();
            return $"{{\"name\":{JsonSerializer.Serialize(j.Name)},\"translation\":[{F(j.X)},{F(j.Y)},{F(j.Z)}]"
                   + (kids.Count > 0 ? $",\"children\":[{string.Join(",", kids)}]" : "") + "}";
        }).Append($"{{\"name\":\"hair\",\"mesh\":0,\"skin\":0}}");
        string json = "{\"asset\":{\"version\":\"2.0\"},\"scene\":0,"
            + $"\"scenes\":[{{\"nodes\":[0,{joints.Length}]}}],\"nodes\":[{string.Join(",", nodes)}],"
            + $"\"skins\":[{{\"joints\":[{string.Join(",", Enumerable.Range(0, joints.Length))}],\"inverseBindMatrices\":3,\"skeleton\":0}}],"
            + "\"meshes\":[{\"name\":\"hair\",\"primitives\":[{\"attributes\":{\"POSITION\":0,\"JOINTS_0\":1,\"WEIGHTS_0\":2}}]}],"
            + $"\"accessors\":[{{\"bufferView\":0,\"componentType\":5126,\"count\":{n},\"type\":\"VEC3\",\"min\":[{string.Join(",", min.Select(v => F(v)))}],\"max\":[{string.Join(",", max.Select(v => F(v)))}]}},"
            + $"{{\"bufferView\":1,\"componentType\":5123,\"count\":{n},\"type\":\"VEC4\"}},"
            + $"{{\"bufferView\":2,\"componentType\":5126,\"count\":{n},\"type\":\"VEC4\"}},"
            + $"{{\"bufferView\":3,\"componentType\":5126,\"count\":{joints.Length},\"type\":\"MAT4\"}}],"
            + $"\"bufferViews\":[{{\"buffer\":0,\"byteOffset\":0,\"byteLength\":{posLen}}},{{\"buffer\":0,\"byteOffset\":{posLen},\"byteLength\":{idxLen}}},"
            + $"{{\"buffer\":0,\"byteOffset\":{posLen + idxLen},\"byteLength\":{wLen}}},{{\"buffer\":0,\"byteOffset\":{posLen + idxLen + wLen},\"byteLength\":{ibmLen}}}],"
            + $"\"buffers\":[{{\"byteLength\":{bin.Length}}}]}}";
        var text = Encoding.UTF8.GetBytes(json);
        int padded = (text.Length + 3) & ~3;
        var data = bin.ToArray();
        int binPadded = (data.Length + 3) & ~3;
        using var ms = new MemoryStream();
        using var w2 = new BinaryWriter(ms);
        w2.Write(0x46546C67u); w2.Write(2u); w2.Write((uint)(12 + 8 + padded + 8 + binPadded));
        w2.Write((uint)padded); w2.Write(0x4E4F534Au); w2.Write(text);
        for (int i = text.Length; i < padded; i++) w2.Write((byte)0x20);
        w2.Write((uint)binPadded); w2.Write(0x004E4942u); w2.Write(data);
        for (int i = data.Length; i < binPadded; i++) w2.Write((byte)0);
        w2.Flush();
        return ms.ToArray();
    }

    private static void NearV(string what, V3 got, double x, double y, double z)
        => Expect(what, Math.Abs(got.X - x) < Tol && Math.Abs(got.Y - y) < Tol && Math.Abs(got.Z - z) < Tol,
                  $"got ({got.X:0.000000}, {got.Y:0.000000}, {got.Z:0.000000}), expected ({x}, {y}, {z})");

    private static void Expect(string what, bool ok, string detail)
    {
        if (!ok) throw new InvalidOperationException($"secondary {what}: {detail}");
    }
}
