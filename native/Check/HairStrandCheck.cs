using System;
using System.Collections.Generic;
using System.Diagnostics;
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
/// The per-strand hair RUNTIME part of <c>--check secondary</c> (hairSim.ts <c>createStrandHair</c> through a real
/// <see cref="Figure"/>, <see cref="StrandHairModifier"/> and the budget of <see cref="FigureManager.TickStrandHair(IEnumerable{Figure}, Vector3?)"/>),
/// on GLBs built here and imported by Godot like every model:
///
///   S1 the binding: the GLB's hair primitive carries <c>_STRAND_CARD</c> / <c>_STRAND_U</c> and ONE vertex no index
///      references (Godot drops it); the handle finds the surface, its Godot→GLB map skips exactly that vertex, card
///      and u land on the right Godot vertices, the head capsule is left out (Ruling H-R7); a record with one card
///      more is refused (StrandMismatch) and the figure keeps its chains.
///   S2 on: the MeshInstance wears an owned clone; every card vertex is skinned to the Head bind alone, the scalp cap
///      keeps its skin; the bytes uploaded equal the vertex buffer Godot itself writes for the same positions and
///      normals (byte for byte); off puts the template's mesh back.
///   S3 gravity: 90 frames at 60 Hz, cards that start horizontal, the head pitching; a twin
///      <see cref="StrandHairDriver"/> on the GLB's own arrays (GLB order, the unreferenced vertex included) posed
///      analytically from the rig; the positions read back from the uploaded bytes equal the twin's at every kept vertex
///      (≤ 1e-5 m; the engine's float bone matrices are the difference), the normals within 1e-3, the tips fall.
///   S4 the budget: four strand figures at 2 / 3 / 4 / 12 m and a first-person one at 1 m; the nearest two run strands
///      (their motion revision ends ":strands", no hair chain left), the third (MaxFigures), the far one and the
///      first-person one keep their chains.
///   S5 bench: the CPU cost per figure of a 400-card hair (sim + rebuild, encode + upload call).
/// </summary>
public static class HairStrandCheck
{
    private const int Rows = StrandSim.Rows;

    private sealed record Joint(string Name, int Parent, double X, double Y, double Z);

    private static readonly Joint[] Rig =
    {
        new("mixamorig:Hips", -1, 0, 0, 0), new("mixamorig:Spine2", 0, 0, 1.3, 0), new("mixamorig:Head", 1, 0, 0.3, 0),
        new("HairGen_c00_00", 2, 0, 0.1, -0.07), new("HairGen_c00_01", 3, 0, -0.1, 0),
    };
    private const int Spine2 = 1, Head = 2, Gen0 = 3, Gen1 = 4;
    private const double HeadY = 1.6;

    /// <summary>The hair primitive in GLB order (the twin binds on these).</summary>
    private sealed record Hair(float[] Pos, float[] Nrm, ushort[] Card, float[] U, int Unreferenced, string RecordJson, byte[] Glb);

    private const string ParamsJson = "{\"damping\":0.04,\"stiffness\":1.0,\"bend\":0.15,\"iterations\":6,\"root_deg\":10,\"root_frac\":0.2,"
        + "\"fly_soft\":true,\"fly_arc\":0.30,\"tether\":true,\"tether_r0\":0.015,\"tether_r1\":0.06,\"tether_head\":0.012,\"head_clr\":0.03,\"face_box\":true}";
    private const string Group = "\"freq_hz\":1,\"zeta\":0.5,\"gravity\":0,\"gravity_scale\":1,\"gain\":1,\"max_deg\":35,\"sag_max_deg\":10,"
        + "\"spill_max_deg\":0,\"head_sag\":1,\"axis_gain\":[1,1,1],\"flatten\":0,\"stretch\":0,\"spread\":0.5,\"flatten_floor\":1,"
        + "\"spill\":0,\"translate\":0,\"squash\":[1,1],\"length\":1,\"girth\":1,\"rest_deg\":0,\"rest_max_deg\":90,\"rigid_tail\":0,"
        + "\"scale_axis\":\"centroid\",\"straighten_deg\":0,\"hair\":true";

    public static string Run(Node3D world)
    {
        var hair = BuildHair(6);
        var plain = GlbLoader.Prepare(hair.Glb);
        var prims = StrandGlb.Read(plain);
        var record = HairStrandRecord.Parse(JsonDocument.Parse(hair.RecordJson).RootElement);
        var chains = MotionPayload.Parse(JsonDocument.Parse($"{{\"rev\":\"h\",\"groups\":{{\"hair_c00\":{{\"bones\":[\"HairGen_c00_00\",\"HairGen_c00_01\"],{Group}}}}}}}").RootElement)!;

        // ---- S1 the binding ----
        var (fig, skel) = Make(world, plain, "Strand", chains, prims, record);
        Expect("S1 the record binds", fig.PrepareStrandHair(), fig.StrandRefusal ?? "");
        var h = fig.StrandHair!;
        int n = hair.Card.Length;
        var expectKept = Enumerable.Range(0, n).Where(v => v != hair.Unreferenced).ToArray();
        Expect("S1 Godot dropped the unreferenced vertex and the map skips it", h.Kept.SequenceEqual(expectKept),
               $"kept {h.Kept.Length} of {n}, unreferenced {hair.Unreferenced}");
        var vk = h.Driver.Sim.Binding.Vk;
        bool cardsRight = expectKept.Select((src, j) => vk[j] == hair.Card[src] - 1).All(x => x);
        Expect("S1 every Godot vertex has its GLB card", cardsRight, "");
        Expect("S1 the head capsule is left out", h.CapsuleIds.SequenceEqual(new[] { "chest" }), string.Join(",", h.CapsuleIds));
        var bad = HairStrandRecord.Parse(JsonDocument.Parse(hair.RecordJson.Replace($"\"cards\":{record.Cards}", $"\"cards\":{record.Cards + 1}")).RootElement);
        var (refused, _) = Make(world, plain, "StrandBad", chains, prims, bad);
        Expect("S1 a record of other cards is refused", !refused.PrepareStrandHair() && refused.StrandHair is null, refused.StrandRefusal ?? "accepted");
        string refusal = refused.StrandRefusal ?? "";
        refused.Free();

        // ---- S2 on: the clone, the Head skin, Godot's own encoding ----
        var templateMesh = h.Mesh.Mesh;
        fig.SetStrandHair(true);
        Expect("S2 strands on", fig.StrandRunning && h.Enabled && h.Mesh.Mesh != templateMesh, "");
        var cloneArrays = ((ArrayMesh)h.Mesh.Mesh).SurfaceGetArrays(h.Surface);
        var tmplArrays = ((ArrayMesh)templateMesh).SurfaceGetArrays(h.Surface);
        var bones = cloneArrays[(int)Mesh.ArrayType.Bones].AsInt32Array();
        var weights = cloneArrays[(int)Mesh.ArrayType.Weights].AsFloat32Array();
        var bones0 = tmplArrays[(int)Mesh.ArrayType.Bones].AsInt32Array();
        var weights0 = tmplArrays[(int)Mesh.ArrayType.Weights].AsFloat32Array();
        const int headBind = Head;   // the GLB skin's joint index = Godot's bind index
        bool headOnly = true, capKept = true;
        for (int j = 0; j < vk.Length; j++)
        {
            if (vk[j] >= 0) headOnly &= bones[4 * j] == headBind && weights[4 * j] == 1 && weights[4 * j + 1] == 0 && weights[4 * j + 2] == 0 && weights[4 * j + 3] == 0;
            else capKept &= Enumerable.Range(0, 4).All(k => bones[4 * j + k] == bones0[4 * j + k] && weights[4 * j + k] == weights0[4 * j + k]);
        }
        Expect("S2 every card vertex is skinned to the Head bind alone", headOnly, "");
        Expect("S2 the scalp cap keeps its skin", capKept, "");
        Expect("S2 the template's skin is untouched", weights0.Where((w, i) => i % 4 == 0).Take(vk.Length).Any(w => w < 1), "");
        var godotBytes = GodotEncoding(cloneArrays, ((ArrayMesh)h.Mesh.Mesh).SurfaceGetFormat(h.Surface), h.Driver.Pos, h.Driver.Nrm);
        Expect("S2 the uploaded bytes are Godot's own encoding", h.Uploaded!.SequenceEqual(godotBytes),
               $"{h.Uploaded!.Length} vs {godotBytes.Length} bytes, first difference at {FirstDiff(h.Uploaded!, godotBytes)}");

        // ---- S3 gravity against the twin ----
        var twin = Twin(hair, record);
        var figWorld = SecondaryMotionModifier.ToAffine(skel.GlobalTransform);
        var root = StrandHairModifier.Mat(SecondaryMotionModifier.ToAffine(fig.GlobalTransform));
        twin.Enable(TwinPose(figWorld, 0, record), root);
        int head = skel.FindBone("mixamorig_Head");
        double worstP = 0, worstN = 0;
        float[] tip0 = TipYs(h, record);
        for (int k = 1; k <= 90; k++)
        {
            double angle = -Math.Min(1, k / 30.0) * 20 * Math.PI / 180;
            fig.UpdateFigure(1.0 / 60);
            skel.SetBonePoseRotation(head, new Quaternion(Vector3.Right, (float)angle));
            h.StepNow(1.0 / 60);
            twin.Update(1.0 / 60, () => TwinPose(figWorld, angle, record), root);
            var (up, un) = StrandUpload.Read(h.Uploaded!, h.Layout);
            for (int j = 0; j < expectKept.Length; j++)
                for (int d = 0; d < 3; d++)
                {
                    worstP = Math.Max(worstP, Math.Abs(up[3 * j + d] - twin.Pos[3 * expectKept[j] + d]));
                    worstN = Math.Max(worstN, Math.Abs(un[3 * j + d] - twin.Nrm[3 * expectKept[j] + d]));
                }
        }
        float[] tip1 = TipYs(h, record);
        double fall = Enumerable.Range(0, tip0.Length).Min(c => tip1[c] - tip0[c]);
        Expect("S3 uploaded positions = the twin's StrandSim (≤ 1e-5 m)", worstP <= 1e-5, $"{worstP:0.###e0} m");
        Expect("S3 uploaded normals = the twin's (≤ 1e-3)", worstN <= 1e-3, $"{worstN:0.###e0}");
        Expect("S3 the uploads ran every frame", h.Uploads >= 90, $"{h.Uploads}");
        Expect("S3 the horizontal cards fell under gravity (tip y, head bind space, > 5 cm)", fall < -0.05, $"{fall * 1000:0.0} mm");
        fig.SetStrandHair(false);
        Expect("S2 off puts the template's mesh back", !h.Enabled && h.Mesh.Mesh == templateMesh, "");
        fig.Free();

        // ---- S4 the budget ----
        var figs = new List<Figure>();
        foreach (var (name, x, z) in new[] { ("A", 2.0, 0.0), ("B", 0.0, 3.0), ("C", -4.0, 0.0), ("D", 12.0, 0.0), ("E", 0.0, -1.0) })
        {
            var (f, _) = Make(world, plain, name, chains, prims, record);
            f.Position = new Vector3((float)x, 0, (float)z);
            figs.Add(f);
        }
        figs[4].SetFirstPerson(true);
        var picked = FigureManager.TickStrandHair(figs, Vector3.Zero);
        foreach (var f in figs) f.UpdateFigure(1.0 / 60);   // the secondary tick sees the changed revision
        static int Chains(Figure f) => f.Secondary is { } s ? s.Motion.ParticleCount + s.Motion.HairCount : -1;   // the chain links solved
        string State(Figure f) => $"{f.CharacterName}:{(f.StrandRunning ? "strands" : "chains")}/{f.Secondary?.Rev}/{Chains(f)}";
        string states = string.Join(" ", figs.Select(State));
        Expect("S4 the nearest two run strands", picked.SetEquals(new[] { "A", "B" }), states);
        Expect("S4 a strand figure solves no hair chain", figs.Take(2).All(f => f.Secondary?.Rev == "h:strands" && Chains(f) == 0), states);
        Expect("S4 beyond the budget (third, far, first person) the chains stay",
               figs.Skip(2).All(f => !f.StrandRunning && f.Secondary?.Rev == "h" && Chains(f) > 0), states);
        picked = FigureManager.TickStrandHair(figs, null);
        Expect("S4 no camera: nobody runs strands", picked.Count == 0 && figs.All(f => !f.StrandRunning), "");
        foreach (var f in figs) f.Free();

        // ---- S5 bench ----
        var big = BuildHair(400);
        var bigPlain = GlbLoader.Prepare(big.Glb);
        var bigRecord = HairStrandRecord.Parse(JsonDocument.Parse(big.RecordJson).RootElement);
        var (bf, bskel) = Make(world, bigPlain, "Bench", chains, StrandGlb.Read(bigPlain), bigRecord);
        Expect("S5 the bench hair binds", bf.PrepareStrandHair(), bf.StrandRefusal ?? "");
        bf.SetStrandHair(true);
        var bh = bf.StrandHair!;
        int bhead = bskel.FindBone("mixamorig_Head");
        double simMs = 0, uploadMs = 0, worstFrame = 0;
        const int frames = 120;
        var sw = new Stopwatch();
        for (int k = 1; k <= frames; k++)
        {
            bf.UpdateFigure(1.0 / 60);
            bskel.SetBonePoseRotation(bhead, new Quaternion(Vector3.Right, (float)(0.3 * Math.Sin(k * 0.1))));
            sw.Restart();
            bh.StepNow(1.0 / 60);
            double ms = sw.Elapsed.TotalMilliseconds;
            if (k > 10) { simMs += ms - bh.LastUploadMs; uploadMs += bh.LastUploadMs; worstFrame = Math.Max(worstFrame, ms); }
        }
        int counted = frames - 10;
        string bench = $"strand bench: {bigRecord.Cards} cards, {bh.Kept.Length} vertices, per figure and frame: sim + rebuild "
                       + $"{simMs / counted:0.00} ms, encode + upload call {uploadMs / counted:0.00} ms (headless: the GPU copy is the dummy's no-op), "
                       + $"worst frame {worstFrame:0.00} ms, cost EMA {bh.Driver.CostMs:0.00} ms";
        GD.Print($"[check-secondary] {bench}");
        bf.Free();

        return $" strands S1..S5 ok (kept {expectKept.Length}/{n}, refused: {refusal}; upload = Godot's bytes; 90 frames vs twin "
               + $"{worstP:0.0e0} m / normals {worstN:0.0e0}, tips fell {-fall * 1000:0} mm; budget {string.Join(",", new[] { "A", "B" })}; {bench})";
    }

    // ---- figures ------------------------------------------------------------------------------------------------------

    private static (Figure, Skeleton3D) Make(Node3D world, byte[] plain, string name, MotionPayload payload,
                                             IReadOnlyList<StrandGlbPrimitive> prims, HairStrandRecord record)
    {
        var (root, _) = GlbLoader.Import(plain, name);
        var skel = ClipLibrary.Find<Skeleton3D>(root) ?? throw new InvalidOperationException($"strands: {name} has no skeleton");
        var fig = new Figure(name) { SecondaryManual = true, Motion = payload, Procedural = false };
        world.AddChild(fig);
        fig.SetYaw(0);
        var body = new Node3D { Name = "Body" };
        body.AddChild(root);
        fig.SetBody(body, true, skel, null);
        fig.SetStrandSource(new StrandHairSource(prims, () => (StrandRecordState.Ready, record)));
        return (fig, skel);
    }

    /// <summary>The tip row's height of every card in head-bind space (the sim's rows through the inverse head).</summary>
    private static float[] TipYs(StrandHairModifier h, HairStrandRecord record)
    {
        var inv = StrandSim.InvertAffine(h.Pose().Head);
        var x = h.Driver.Sim.X;
        return Enumerable.Range(0, record.Cards).Select(c =>
        {
            int o = 3 * (c * Rows + Rows - 1);
            return (float)(inv[1] * x[o] + inv[5] * x[o + 1] + inv[9] * x[o + 2] + inv[13]);
        }).ToArray();
    }

    // ---- the twin -----------------------------------------------------------------------------------------------------

    private static StrandHairDriver Twin(Hair hair, HairStrandRecord record)
    {
        var sim = new StrandSim(StrandSim.Bind(record, hair.Pos, hair.Nrm, hair.Card, hair.U), record);
        var own = StrandSim.RecordCapsules(record).Where(c => c.Region != StrandHairModifier.SkippedRegion).ToList();
        var binds = own.Select(c => new StrandBind(new[] { c.APos!.Value.X, c.APos.Value.Y, c.APos.Value.Z },
                                                   new[] { c.BPos!.Value.X, c.BPos.Value.Y, c.BPos.Value.Z })).ToList();
        return new StrandHairDriver(record, sim, binds);
    }

    /// <summary>The rig's pose by hand: Spine2 still, Head pitched by <paramref name="angle"/> about +X at its joint
    /// (bind→world = skeleton · T(head) · R · T(−head)); the chest capsule through Spine2 (the skeleton frame).</summary>
    private static StrandPose TwinPose(Affine skeleton, double angle, HairStrandRecord record)
    {
        double c = Math.Cos(angle), s = Math.Sin(angle);
        var r = new Affine(1, 0, 0, 0, c, s, 0, -s, c, 0, 0, 0);
        var head = skeleton.Times(Affine.Translation(0, HeadY, 0)).Times(r).Times(Affine.Translation(0, -HeadY, 0));
        var spine = skeleton;
        var follow = record.FollowBones.Select(b => StrandHairModifier.Mat(BoneNames.Norm(b) == "head" ? head : spine)).ToArray();
        var caps = StrandSim.RecordCapsules(record).Where(cc => cc.Region != StrandHairModifier.SkippedRegion).Select(cc =>
        {
            var a = spine.Apply(cc.APos!.Value.X, cc.APos.Value.Y, cc.APos.Value.Z);
            var b = spine.Apply(cc.BPos!.Value.X, cc.BPos.Value.Y, cc.BPos.Value.Z);
            return (new[] { a.X, a.Y, a.Z }, new[] { b.X, b.Y, b.Z }, cc.R * Collision.LinearScale(spine));
        }).ToArray();
        return new StrandPose { Follow = follow, Head = StrandHairModifier.Mat(head), Capsules = caps };
    }

    /// <summary>The vertex buffer Godot writes itself for <paramref name="arrays"/> with these positions and normals.</summary>
    private static byte[] GodotEncoding(Godot.Collections.Array arrays, Mesh.ArrayFormat format, float[] pos, float[] nrm)
    {
        var a = arrays.Duplicate();
        int n = pos.Length / 3;
        var p = new Vector3[n]; var q = new Vector3[n];
        for (int i = 0; i < n; i++) { p[i] = new Vector3(pos[3 * i], pos[3 * i + 1], pos[3 * i + 2]); q[i] = new Vector3(nrm[3 * i], nrm[3 * i + 1], nrm[3 * i + 2]); }
        a[(int)Mesh.ArrayType.Vertex] = p;
        a[(int)Mesh.ArrayType.Normal] = q;
        var m = new ArrayMesh();
        m.AddSurfaceFromArrays(Mesh.PrimitiveType.Triangles, a, null, null, format & ~Mesh.ArrayFormat.FlagCompressAttributes);
        return RenderingServer.MeshGetSurface(m.GetRid(), 0)["vertex_data"].AsByteArray();
    }

    private static int FirstDiff(byte[] a, byte[] b)
    {
        for (int i = 0; i < Math.Min(a.Length, b.Length); i++) if (a[i] != b[i]) return i;
        return a.Length == b.Length ? -1 : Math.Min(a.Length, b.Length);
    }

    // ---- the GLB and its record ------------------------------------------------------------------------------------

    /// <summary>
    /// <paramref name="cards"/> straight cards of 17 rows, 2 cm apart, rooted on a 9 cm ring 5 cm above the head joint and
    /// running out HORIZONTALLY (2 vertices per row, ±4 mm sideways, normals up; skinned half Head, half Spine2), a
    /// 4-vertex scalp cap (card 0), one triangle per hair-chain joint (card 0), and one vertex no index references.
    /// The record: rows in bind space (= geometry space), 2 pins, follow [Head, Spine2] = pins {Head 1}, free {.5, .5},
    /// an SDF grid far away (every row "outside"), face/eye boxes far away, capsules head (Head) + chest (Spine2).
    /// </summary>
    private static Hair BuildHair(int cards)
    {
        var pos = new List<float>(); var nrm = new List<float>(); var card = new List<ushort>(); var u = new List<float>();
        var joints = new List<ushort>(); var wts = new List<float>(); var idx = new List<uint>();
        var rest = new List<double>(); var pins = new List<double>(); var freeArc = new List<double>(); var freeFrac = new List<double>(); var w = new List<double>();
        void V(double x, double y, double z, ushort c, double uu, int j0, float w0, int j1, float w1)
        {
            pos.Add((float)x); pos.Add((float)y); pos.Add((float)z); nrm.Add(0); nrm.Add(1); nrm.Add(0);
            card.Add(c); u.Add((float)uu);
            joints.AddRange(new[] { (ushort)j0, (ushort)j1, (ushort)0, (ushort)0 }); wts.AddRange(new[] { w0, w1, 0f, 0f });
        }
        // the scalp cap
        foreach (var (x, z) in new[] { (-0.02, -0.02), (0.02, -0.02), (0.02, 0.02), (-0.02, 0.02) }) V(x, HeadY + 0.095, z, 0, 0, Head, 1, 0, 0);
        idx.AddRange(new uint[] { 0, 2, 1, 0, 3, 2 });
        int unreferenced = pos.Count / 3;
        V(0, HeadY + 0.2, 0, 1, 0, Head, 1, 0, 0);   // in the list, in no triangle
        const int pinCount = 2;
        for (int k = 0; k < cards; k++)
        {
            double th = 2 * Math.PI * (k + 0.5) / cards, dx = Math.Cos(th), dz = Math.Sin(th);
            double sx = -dz, sz = dx;
            int first = pos.Count / 3;
            for (int i = 0; i < Rows; i++)
            {
                double px = 0.09 * dx + 0.02 * i * dx, py = HeadY + 0.05, pz = 0.09 * dz + 0.02 * i * dz;
                rest.Add(px); rest.Add(py); rest.Add(pz);
                double fa = i < pinCount ? 0 : 0.02 * (i - (pinCount - 1));
                freeArc.Add(fa); freeFrac.Add(i < pinCount ? 0 : fa / (0.02 * (Rows - pinCount)));
                if (i < pinCount) { w.Add(1); w.Add(0); } else { w.Add(0.5); w.Add(0.5); }
                foreach (int sgn in new[] { -1, 1 }) V(px + sgn * 0.004 * sx, py, pz + sgn * 0.004 * sz, (ushort)(k + 1), i, Head, 0.5f, Spine2, 0.5f);
            }
            pins.Add(pinCount);
            for (int i = 0; i + 1 < Rows; i++)
            {
                uint a = (uint)(first + 2 * i), b = a + 1, c = a + 2, d = a + 3;
                idx.AddRange(new[] { a, c, b, b, c, d });
            }
        }
        // one small triangle per hair-chain joint (the scalp's chain-driven part, card 0)
        foreach (var (j, y, z) in new[] { (Gen0, HeadY + 0.1, -0.07), (Gen1, HeadY, -0.07) })
        {
            uint at = (uint)(pos.Count / 3);
            V(-0.001, y, z, 0, 0, j, 1, 0, 0); V(0.001, y, z, 0, 0, j, 1, 0, 0); V(0, y, z + 0.001, 0, 0, j, 1, 0, 0);
            idx.AddRange(new[] { at, at + 1, at + 2 });
        }
        var sdf = Convert.ToBase64String(Enumerable.Repeat((byte)127, 8).ToArray());
        string F(double v) => v.ToString("R", System.Globalization.CultureInfo.InvariantCulture);
        string Arr(IEnumerable<double> v) => "[" + string.Join(",", v.Select(F)) + "]";
        string recordJson = "{\"version\":2,\"item_id\":\"hair_check\",\"fsig\":\"0123456789ab\",\"mode\":\"hairdeck\",\"fit_sha256\":\"check\","
            + $"\"frame\":\"head_bind\",\"head_bone\":\"mixamorig:Head\",\"rows\":{Rows},\"cards\":{cards},"
            + $"\"rest\":{Arr(rest)},\"pins\":{Arr(pins)},\"free_arc\":{Arr(freeArc)},\"free_frac\":{Arr(freeFrac)},"
            + $"\"follow\":{{\"bones\":[\"mixamorig:Head\",\"mixamorig:Spine2\"],\"w\":{Arr(w)}}},\"ear_y\":{F(HeadY - 0.04)},"
            + "\"face_box\":[9,9.1,9,9.1,9],\"eye_box\":[9,9.1,9,9.1,9],"
            + $"\"sdf\":{{\"dims\":[2,2,2],\"lo\":[5,5,5],\"vox\":0.01,\"order\":\"x_fastest\",\"unit\":\"mm_int8\",\"data\":\"{sdf}\"}},"
            + "\"capsules\":{\"version\":9,\"capsules\":[{\"id\":\"head\",\"a\":\"mixamorig:Head\",\"b\":\"mixamorig:Head\",\"r\":0.09,\"region\":\"head\"},"
            + "{\"id\":\"chest\",\"a\":\"mixamorig:Spine2\",\"b\":\"mixamorig:Spine2\",\"r\":0.08,\"region\":\"torso\",\"a_pos\":[0,1.0,0],\"b_pos\":[0,1.45,0]}]},"
            + $"\"params\":{ParamsJson},\"vertex_attributes\":{{\"card\":\"_STRAND_CARD\",\"u\":\"_STRAND_U\"}}}}";
        var glb = Glb(pos.ToArray(), nrm.ToArray(), joints.ToArray(), wts.ToArray(), card.ToArray(), u.ToArray(), idx.ToArray());
        return new Hair(pos.ToArray(), nrm.ToArray(), card.ToArray(), u.ToArray(), unreferenced, recordJson, glb);
    }

    /// <summary>The rig, a body mesh (one triangle on Spine2 and one on Head, the BODY skin the capsules bind to) and the
    /// hair mesh under a node named <c>garment_hair</c>; both on one skin; inverse binds = the joints' inverse world translations.</summary>
    private static byte[] Glb(float[] pos, float[] nrm, ushort[] joints, float[] wts, ushort[] card, float[] u, uint[] idx)
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
        string F(double v) => v.ToString("R", System.Globalization.CultureInfo.InvariantCulture);
        int Add(byte[] data, int componentType, string type, int count, string extra = "")
        {
            while (bin.Length % 4 != 0) bin.WriteByte(0);
            views.Add($"{{\"buffer\":0,\"byteOffset\":{bin.Length},\"byteLength\":{data.Length}}}");
            bin.Write(data);
            accessors.Add($"{{\"bufferView\":{views.Count - 1},\"componentType\":{componentType},\"count\":{count},\"type\":\"{type}\"{extra}}}");
            return accessors.Count - 1;
        }
        byte[] Bytes<T>(T[] a) where T : struct => System.Runtime.InteropServices.MemoryMarshal.AsBytes(a.AsSpan()).ToArray();
        string MinMax(float[] p)
        {
            var mn = Enumerable.Range(0, 3).Select(a => Enumerable.Range(0, p.Length / 3).Min(v => p[3 * v + a]));
            var mx = Enumerable.Range(0, 3).Select(a => Enumerable.Range(0, p.Length / 3).Max(v => p[3 * v + a]));
            return $",\"min\":[{string.Join(",", mn.Select(x => F(x)))}],\"max\":[{string.Join(",", mx.Select(x => F(x)))}]";
        }
        int nv = pos.Length / 3;
        int hPos = Add(Bytes(pos), 5126, "VEC3", nv, MinMax(pos));
        int hNrm = Add(Bytes(nrm), 5126, "VEC3", nv);
        int hJ = Add(Bytes(joints), 5123, "VEC4", nv);
        int hW = Add(Bytes(wts), 5126, "VEC4", nv);
        int hCard = Add(Bytes(card), 5123, "SCALAR", nv);
        int hU = Add(Bytes(u), 5126, "SCALAR", nv);
        int hIdx = Add(Bytes(idx), 5125, "SCALAR", idx.Length);
        var bodyPos = new float[] { -0.01f, 1.3f, 0, 0.01f, 1.3f, 0, 0, 1.3f, 0.01f, -0.01f, 1.6f, 0, 0.01f, 1.6f, 0, 0, 1.6f, 0.01f };
        var bodyNrm = Enumerable.Range(0, 6).SelectMany(_ => new[] { 0f, 1, 0 }).ToArray();
        var bodyJ = new ushort[] { Spine2, 0, 0, 0, Spine2, 0, 0, 0, Spine2, 0, 0, 0, Head, 0, 0, 0, Head, 0, 0, 0, Head, 0, 0, 0 };
        var bodyW = Enumerable.Range(0, 6).SelectMany(_ => new[] { 1f, 0, 0, 0 }).ToArray();
        int bPos = Add(Bytes(bodyPos), 5126, "VEC3", 6, MinMax(bodyPos));
        int bNrm = Add(Bytes(bodyNrm), 5126, "VEC3", 6);
        int bJ = Add(Bytes(bodyJ), 5123, "VEC4", 6);
        int bW = Add(Bytes(bodyW), 5126, "VEC4", 6);
        var ibm = world.SelectMany(p => new[] { 1f, 0, 0, 0, 0, 1, 0, 0, 0, 0, 1, 0, (float)-p.X, (float)-p.Y, (float)-p.Z, 1 }).ToArray();
        int hIbm = Add(Bytes(ibm), 5126, "MAT4", Rig.Length);
        var nodes = Rig.Select((j, i) =>
        {
            var kids = Enumerable.Range(0, Rig.Length).Where(c => Rig[c].Parent == i).ToList();
            return $"{{\"name\":{JsonSerializer.Serialize(j.Name)},\"translation\":[{F(j.X)},{F(j.Y)},{F(j.Z)}]"
                   + (kids.Count > 0 ? $",\"children\":[{string.Join(",", kids)}]" : "") + "}";
        }).Append("{\"name\":\"body\",\"mesh\":0,\"skin\":0}").Append("{\"name\":\"garment_hair\",\"mesh\":1,\"skin\":0}");
        string json = "{\"asset\":{\"version\":\"2.0\"},\"scene\":0,"
            + $"\"scenes\":[{{\"nodes\":[0,{Rig.Length},{Rig.Length + 1}]}}],\"nodes\":[{string.Join(",", nodes)}],"
            + $"\"skins\":[{{\"joints\":[{string.Join(",", Enumerable.Range(0, Rig.Length))}],\"inverseBindMatrices\":{hIbm},\"skeleton\":0}}],"
            + $"\"meshes\":[{{\"name\":\"body\",\"primitives\":[{{\"attributes\":{{\"POSITION\":{bPos},\"NORMAL\":{bNrm},\"JOINTS_0\":{bJ},\"WEIGHTS_0\":{bW}}}}}]}},"
            + $"{{\"name\":\"hair\",\"primitives\":[{{\"attributes\":{{\"POSITION\":{hPos},\"NORMAL\":{hNrm},\"JOINTS_0\":{hJ},\"WEIGHTS_0\":{hW},"
            + $"\"_STRAND_CARD\":{hCard},\"_STRAND_U\":{hU}}},\"indices\":{hIdx}}}]}}],"
            + $"\"accessors\":[{string.Join(",", accessors)}],\"bufferViews\":[{string.Join(",", views)}],"
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

    private static void Expect(string what, bool ok, string detail)
    {
        if (!ok) throw new InvalidOperationException($"secondary {what}: {detail}");
    }
}
