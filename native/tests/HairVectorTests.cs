using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using AnimaNative.Figures;
using AnimaNative.Overview;
using AnimaNative.Tests.Vectors;
using Xunit;
using static AnimaNative.Tests.ScatterVectorAdapters;

namespace AnimaNative.Tests;

/// <summary>
/// The adapters of scripts/export_hair_vectors.mjs (the hair-chain port, stages 1 and 2), mirrored for the native port.
/// The vectors are the TypeScript's output (collision.ts, garmentCollision.ts, secondaryMotion.ts); every case states
/// its tolerance in the file (1e-9 for the pure core, 1e-6 m for the end-to-end chains):
/// <code>
///   TS fn               C#                                        shape translation
///   jointNowFrom        Collision.JointNowFrom                    column-major 16 ↔ Affine (the last row is 0 0 0 1)
///   capsuleNow          Collision.CapsuleNowOf                    {r, a_pos?, b_pos?} ↔ CollisionCapsule
///   linearScale         Collision.LinearScale
///   tipBindFactors      Collision.TipBindFactors
///   hairChainCapsules   Collision.HairChainCapsules               [{id, a, region?}] → ids
///   pushOutOfCapsules   Collision.PushOutOfCapsules               [{a, b, r, bind?{a, b}}], weight, bindP|null, squeeze
///   contactAngleTurn    Collision.HairTipTurn                     → {angle, axis, depth0} | null
///   bindCollision       CollisionBinding.Bind + Update            three rig → MotionRig (root = Base), one skin over every
///                                                                 bone: boneInverse = inverse bind world, bindMatrix =
///                                                                 the mesh's bind world; update with the posed mesh
///                                                                 world and its inverse (three's attached bind mode)
///   hairChain           MotionRig + SecondaryMotion (+ SetCollision) the chain fixture; per frame Configure(payload) when
///                                                                 the frame names one, the posed bones' local rotation and
///                                                                 the moved bones' local position (the rest kept), then
///                                                                 Update(dt); recorded world matrices; ContactTips
/// </code>
/// </summary>
internal static class HairVectorAdapters
{
    private static double N(JsonNode? n) => VectorCompare.Num(n);
    private static V3 Vec(JsonNode? n) => new(N(n![0]), N(n[1]), N(n[2]));
    private static V3? VecOrNull(JsonNode? n) => n is null ? null : Vec(n);
    private static JsonArray Arr(V3 v) => new(v.X, v.Y, v.Z);
    private static Affine Mat(JsonNode? n) => MotionMath.FromElements(((JsonArray)n!).Select(x => N(x)).ToArray());
    private static JsonArray MatJson(Affine m) => new(m.Elements().Select(x => (JsonNode?)x).ToArray());
    /// <summary>three: Matrix4.fromArray(m).decompose(position, quaternion, scale), recomposed on update.</summary>
    private static Affine Trs(JsonNode? n)
    {
        var (p, q, s) = RigMath.Decompose(Mat(n));
        return RigMath.Compose(p, q, s);
    }
    private static JsonObject CapsuleJson(CapsuleNow c) => new() { ["a"] = Arr(c.A), ["b"] = Arr(c.B), ["r"] = c.R };

    private static List<CollideCapsule> Capsules(JsonNode? n)
        => ((JsonArray)n!).Select(c => new CollideCapsule(Vec(c!["a"]), Vec(c["b"]), N(c["r"]),
                                                           VecOrNull(c["bind"]?["a"]), VecOrNull(c["bind"]?["b"]))).ToList();

    private static JointNow Joint(JsonNode? n) => new(Vec(n!["position"]), Mat(n["bindToWorld"]));

    private static CollisionPayload? Payload(JsonNode? n) => n is null ? null : CollisionPayload.Parse(SecondaryVectorAdapters.Element(n));

    private static MotionRig Rig(JsonObject d, out Affine[] bindLocal)
    {
        var bones = (JsonArray)d["bones"]!;
        var rig = new MotionRig(bones.Select(b => Str(b!["name"])).ToList(),
                                bones.Select(b => b!["parent"] is { } p ? (int)N(p) : -1).ToList());
        if (d["root"] is { } root) rig.Base = Trs(root);
        for (int i = 0; i < bones.Count; i++) rig.Local[i] = Trs(bones[i]!["matrix"]);
        rig.UpdateWorld();
        bindLocal = rig.Local.ToArray();
        return rig;
    }

    public static JsonNode? BindCollision(JsonNode? node)
    {
        var d = (JsonObject)node!;
        var rig = Rig(d, out _);
        var meshLocal = d["mesh"] is { } m ? Trs(m) : Affine.Identity;
        var bindMatrix = rig.Base.Times(meshLocal);
        var joints = new Dictionary<string, BodyJoint>();
        for (int i = 0; i < rig.Count; i++) joints.TryAdd(BoneNames.Norm(rig.Names[i]), new BodyJoint(i, rig.World[i].Inverted()));
        var binding = CollisionBinding.Bind(Payload(d["payload"]), joints, bindMatrix);
        if (binding is null) return null;
        if (d["pose"]?["root"] is { } root) rig.Base = Trs(root);
        foreach (var e in (JsonArray?)d["pose"]?["bones"] ?? new JsonArray()) rig.Local[(int)N(e![0])] = Trs(e[1]);
        rig.UpdateWorld();
        var meshWorld = rig.Base.Times(meshLocal);
        binding.Update(n => rig.World[n], meshWorld, meshWorld.Inverted());
        return new JsonObject
        {
            ["capsules"] = new JsonArray(binding.Capsules.Select(e => (JsonNode?)new JsonObject
                { ["id"] = e.Capsule.Id, ["now"] = CapsuleJson(e.Now), ["bind"] = CapsuleJson(e.Bind) }).ToArray()),
            ["missing"] = new JsonArray(binding.Missing.Select(x => (JsonNode?)x).ToArray()),
        };
    }

    public static JsonNode? HairChain(JsonNode? node)
    {
        var d = (JsonObject)node!;
        var rig = Rig(d, out var bindLocal);
        var inverses = rig.World.Select(w => w.Inverted()).ToArray();
        float[] F(string k) => ((JsonArray)d[k]!).Select(x => (float)N(x)).ToArray();
        var skin = new MotionSkin(Enumerable.Range(0, rig.Count).ToArray(), inverses, F("positions"),
                                  ((JsonArray)d["indices"]!).Select(x => (int)N(x)).ToArray(), F("weights"));
        var centroids = SecondaryMotion.MeasureCentroids(new[] { skin });
        var motion = new SecondaryMotion(rig, skin.JointNodes, centroids, _ => null,
                                         MotionPayload.Parse(SecondaryVectorAdapters.Element(d["payload"])),
                                         SecondaryMotion.MeasureReach(new[] { skin }, centroids));
        if (Payload(d["collision"]) is { } collision)
            motion.SetCollision(collision, Enumerable.Range(0, rig.Count).Select(i => (i, inverses[i])));
        var record = ((JsonArray)d["record"]!).Select(x => (int)N(x)).ToHashSet();
        var pose = bindLocal.ToArray();
        // three keeps position, quaternion and scale per bone: a frame sets the ones it names, the rest stay.
        var parts = bindLocal.Select(RigMath.Decompose).ToArray();
        var frames = new JsonArray();
        int k = 0;
        foreach (var f in (JsonArray)d["frames"]!)
        {
            k++;
            if (f!["configure"] is { } configure) motion.Configure(MotionPayload.Parse(SecondaryVectorAdapters.Element(configure)));
            var touched = new HashSet<int>();
            foreach (var e in (JsonArray?)f["pose"] ?? new JsonArray())
            {
                int i = (int)N(e![0]);
                parts[i].Rotation = new Quat(N(e[1]), N(e[2]), N(e[3]), N(e[4]));
                touched.Add(i);
            }
            foreach (var e in (JsonArray?)f["move"] ?? new JsonArray())
            {
                int i = (int)N(e![0]);
                parts[i].Position = new V3(N(e[1]), N(e[2]), N(e[3]));
                touched.Add(i);
            }
            foreach (int i in touched) pose[i] = RigMath.Compose(parts[i].Position, parts[i].Rotation, parts[i].Scale);
            for (int i = 0; i < rig.Count; i++) rig.Local[i] = pose[i];
            rig.UpdateWorld();   // three: root.updateMatrixWorld(true) before update (a motion with nothing to drive returns)
            motion.Update(N(f["dt"]));
            if (record.Contains(k))
                frames.Add(new JsonObject { ["frame"] = k, ["matrices"] = new JsonArray(rig.World.Select(w => (JsonNode?)MatJson(w)).ToArray()) });
        }
        var tips = new JsonArray(motion.ContactTips().Select(t => (JsonNode?)new JsonObject
        {
            ["bone"] = t.Bone, ["capsules"] = new JsonArray(t.Capsules.Select(x => (JsonNode?)x).ToArray()),
            ["tip"] = Arr(t.Tip), ["tipLocal"] = Arr(t.TipLocal),
        }).ToArray());
        return new JsonObject { ["frames"] = frames, ["tips"] = tips };
    }

    public static readonly Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch = new()
    {
        ["jointNowFrom"] = a =>
        {
            Arity(a, 5, 5);
            var j = Collision.JointNowFrom(Mat(a[0]), Mat(a[1]), Mat(a[2]), Mat(a[3]), Mat(a[4]));
            return new JsonObject { ["position"] = Arr(j.Position), ["bindToWorld"] = MatJson(j.BindToWorld) };
        },
        ["capsuleNow"] = a =>
        {
            Arity(a, 3, 3);
            var c = a[0]!;
            var capsule = new CollisionCapsule("", "", "", N(c["r"]), "", VecOrNull(c["a_pos"]), VecOrNull(c["b_pos"]));
            return CapsuleJson(Collision.CapsuleNowOf(capsule, Joint(a[1]), Joint(a[2])));
        },
        ["linearScale"] = a => Collision.LinearScale(Mat(Arity(a, 1, 1)[0])),
        ["tipBindFactors"] = a =>
        {
            Arity(a, 2, 2);
            var caps = ((JsonArray)a[1]!).Select(c => new CapsuleNow(Vec(c!["a"]), Vec(c["b"]), N(c["r"]))).ToList();
            return new JsonArray(Collision.TipBindFactors(Vec(a[0]), caps).Select(x => (JsonNode?)x).ToArray());
        },
        ["hairChainCapsules"] = a =>
        {
            var list = (JsonArray)Arity(a, 1, 1)[0]!;
            return new JsonArray(Collision.HairChainCapsules(list, c => c!["region"]?.GetValue<string>() ?? "")
                                          .Select(c => (JsonNode?)Str(c!["id"])).ToArray());
        },
        ["pushOutOfCapsules"] = a =>
        {
            Arity(a, 5, 5);
            return Arr(Collision.PushOutOfCapsules(Vec(a[0]), Capsules(a[1]), N(a[2]), VecOrNull(a[3]), a[4]!.GetValue<bool>()));
        },
        ["contactAngleTurn"] = a =>
        {
            Arity(a, 4, 4);
            return Collision.HairTipTurn(Vec(a[0]), Vec(a[1]), Capsules(a[2]), N(a[3])) is { } t
                ? new JsonObject { ["angle"] = t.Angle, ["axis"] = Arr(t.Axis), ["depth0"] = t.Depth0 } : null;
        },
        ["bindCollision"] = a => BindCollision(Arity(a, 1, 1)[0]),
        ["hairChain"] = a => HairChain(Arity(a, 1, 1)[0]),
    };
}

/// <summary>shared/test-vectors/collision_core.json (the collision core; generated by scripts/export_hair_vectors.mjs).</summary>
public class CollisionCoreVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("collision_core"));
    public static TheoryData<string> Cases => VectorFile.Labels("collision_core");

    [Theory]
    [MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, HairVectorAdapters.Dispatch);

    [Fact]
    public void EveryFunctionIsDispatched() => Assert.Empty(File.Value.MissingFunctions(HairVectorAdapters.Dispatch));
}

/// <summary>shared/test-vectors/hair_chains.json (hair chains end to end; generated by scripts/export_hair_vectors.mjs).</summary>
public class HairChainVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("hair_chains"));
    public static TheoryData<string> Cases => VectorFile.Labels("hair_chains");

    [Theory]
    [MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, HairVectorAdapters.Dispatch);

    [Fact]
    public void EveryFunctionIsDispatched() => Assert.Empty(File.Value.MissingFunctions(HairVectorAdapters.Dispatch));
}

/// <summary>
/// shared/test-vectors/rigid_shaft.json (the RIGID SHAFT end to end on the fixture of scripts/smoke_rigid_shaft.mjs;
/// generated by scripts/export_hair_vectors.mjs, 1e-8 per number), and r = 0 against an absent r bit for bit.
/// </summary>
public class RigidShaftVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("rigid_shaft"));
    public static TheoryData<string> Cases => VectorFile.Labels("rigid_shaft");

    [Theory]
    [MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, HairVectorAdapters.Dispatch);

    [Fact]
    public void EveryFunctionIsDispatched() => Assert.Empty(File.Value.MissingFunctions(HairVectorAdapters.Dispatch));

    /// <summary>A shake with gravity and an own capsule: rigid 0 gives exactly the numbers of a payload without rigid.</summary>
    [Fact]
    public void RigidZeroIsTheFreeChainBitForBit()
    {
        string Run(string rigid)
        {
            var frames = string.Join(",", Enumerable.Range(0, 60).Select(i =>
                "{\"dt\":0.016666666666666666,\"move\":[[0,0,0," + (0.05 * Math.Sin(2 * Math.PI * 1.5 * i / 60)).ToString("R", System.Globalization.CultureInfo.InvariantCulture) + "]]}"));
            var json = "{\"bones\":[{\"name\":\"mixamorig:Hips\",\"parent\":null,\"matrix\":[1,0,0,0,0,1,0,0,0,0,1,0,0,0,0,1]},"
                + "{\"name\":\"mixamorig:ShaftA\",\"parent\":0,\"matrix\":[1,0,0,0,0,1,0,0,0,0,1,0,0,1,0,1]},"
                + "{\"name\":\"mixamorig:ShaftB\",\"parent\":1,\"matrix\":[1,0,0,0,0,1,0,0,0,0,1,0,1,0,0,1]},"
                + "{\"name\":\"mixamorig:ShaftC\",\"parent\":2,\"matrix\":[1,0,0,0,0,1,0,0,0,0,1,0,1,0,0,1]}],"
                + "\"positions\":[0.5,1,0,1.5,1,0,2.5,1,0],\"indices\":[1,0,0,0,2,0,0,0,3,0,0,0],\"weights\":[1,0,0,0,1,0,0,0,1,0,0,0],"
                + "\"payload\":{\"rev\":\"f\",\"groups\":{\"tail_chain\":{\"bones\":[\"ShaftA\",\"ShaftB\",\"ShaftC\"],\"hair\":true,"
                + "\"freq_hz\":2,\"zeta\":0.3,\"gravity\":0.5,\"gravity_scale\":2,\"gain\":1,\"max_deg\":25,\"sag_max_deg\":30,"
                + "\"translate\":0.3,\"spill\":0.2,\"squash\":[0.8,1.2],\"rest_deg\":0,\"rest_max_deg\":90" + rigid + "}}},"
                + "\"collision\":{\"version\":" + Collision.Version + ",\"capsules\":[{\"id\":\"end\",\"a\":\"mixamorig:Hips\",\"b\":\"mixamorig:Hips\","
                + "\"r\":0.05,\"region\":\"head\",\"a_pos\":[2.5,0.93,-1],\"b_pos\":[2.5,0.93,1]}]},"
                + "\"frames\":[" + frames + "],\"record\":[" + string.Join(",", Enumerable.Range(1, 60)) + "]}";
            return HairVectorAdapters.HairChain(JsonNode.Parse(json))!.ToJsonString();
        }
        string absent = Run(""), zero = Run(",\"rigid\":0");
        Assert.Contains("\"capsules\":[\"end\"]", absent);   // the contact ran
        Assert.Equal(absent, zero);
    }
}

/// <summary>The payload readers of the port, every value by hand.</summary>
public class HairPayloadTests
{
    [Fact]
    public void MotionGroupReadsTheHairFields()
    {
        var g = MotionGroup.Parse(JsonDocument.Parse("{\"bones\":[],\"hair\":true,\"anchor_from\":\"mixamorig:Head\","
            + "\"anchor_blend\":{\"HairGen_c00_02\":{\"mixamorig:Head\":0.5,\"mixamorig:Spine2\":\"0.5\",\"x\":{}},\"bad\":3}}").RootElement);
        Assert.True(g.Hair);
        Assert.Equal("mixamorig:Head", g.AnchorFrom);
        Assert.Equal(2, g.AnchorBlend!.Count);
        var row = g.AnchorBlend[0].Row!;
        Assert.Equal(("mixamorig:Head", 0.5), row[0]);
        Assert.Equal(("mixamorig:Spine2", 0.5), row[1]);   // JS Number("0.5")
        Assert.True(double.IsNaN(row[2].Share));            // Number({}) — dropped by the reader
        Assert.Null(g.AnchorBlend[1].Row);                  // a row that is no object: no blend
        Assert.False(MotionGroup.Parse(JsonDocument.Parse("{\"bones\":[\"a\"]}").RootElement).Hair);
        // A rows-only group activates the motion: its carried joints count as group bones.
        var p = MotionPayload.Parse(JsonDocument.Parse("{\"rev\":\"r\",\"groups\":{\"h\":{\"bones\":[],\"hair\":true,"
            + "\"anchor_blend\":{\"HairGen_c00_02\":{\"mixamorig:Head\":1}}}}}").RootElement)!;
        Assert.Empty(p.BoneKeys());
        Assert.Equal(new[] { "hairgen_c00_02" }, p.MatchKeys());
        Assert.True(SecondaryMotion.Matches(new MotionRig(new[] { "HairGen_c00_02" }, new[] { -1 }), p));
    }

    [Fact]
    public void CollisionPayloadParse()
    {
        var model = JsonDocument.Parse("{\"collision\":{\"version\":9,\"capsules\":[{\"id\":\"head\",\"a\":\"mixamorig:Head\","
            + "\"b\":\"mixamorig:Head\",\"r\":0.09,\"region\":\"head\",\"a_pos\":[0,1.8,0.03]},{\"id\":\"x\",\"a\":\"A\",\"b\":\"B\"}],"
            + "\"channels\":[]}}").RootElement;
        var c = CollisionPayload.Of(model)!;
        Assert.Equal(9, c.Version);
        Assert.Equal(2, c.Capsules.Count);
        Assert.Equal(new V3(0, 1.8, 0.03), c.Capsules[0].APos);
        Assert.Null(c.Capsules[0].BPos);
        Assert.True(double.IsNaN(c.Capsules[1].R));   // no radius: the binding leaves it out (!(r > 0))
        Assert.Equal("", c.Capsules[1].Region);
        Assert.Null(CollisionPayload.Of(JsonDocument.Parse("{\"collision\":null}").RootElement));
        Assert.Null(CollisionPayload.Of(JsonDocument.Parse("{}").RootElement));
    }
}
