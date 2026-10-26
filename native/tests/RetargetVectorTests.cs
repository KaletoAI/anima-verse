using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json.Nodes;
using AnimaNative.Figures;
using AnimaNative.Tests.Vectors;
using Xunit;
using static AnimaNative.Tests.ScatterVectorAdapters;

namespace AnimaNative.Tests;

/// <summary>
/// shared/test-vectors/retarget.json against <see cref="RestCorrections"/> (hand derivations:
/// scripts/smoke_clip_retarget.mjs [1]–[10]). The adapter is the C# twin of scripts/retargetVectorDispatch.mjs:
/// it ASSEMBLES the input poses from the JSON bone rows (local rotations as axis-angle turns, local offsets, the
/// armature turn, sole points relative to each ankle) with quaternion/rigid-transform algebra, never the expected
/// output.
/// <code>
///   vector fn                      C#
///   retargetFactors                RestCorrections.Build → {bone: {left, right}}
///   retargetKeys / retargetHas     RestCorrections.Build keys (target walk order)
///   retargetDrive                  RestCorrections.Apply(K, c)
///   retargetDeformation            Apply(K, c)·R_t⁻¹
///   retargetWorld                  chain of Apply(K, c) from the target armature
///   retargetConstantDeformations   donor vs target world deformation per bone
///   retargetPositions              rigid chain with Apply(K, c) (stance results as positions)
///   retargetSoleDeltas             heel − toe through the foot's K_b (foot stance)
///   bindRelativeValues             RestCorrections.BindRelativeValues
///   bindRelativeClipSummary        RestCorrections.BindRelativeClip (object identity of clip and tracks)
///   retargetCounterProbe           pure quaternion algebra of the two wrong rules
/// </code>
/// </summary>
public class RetargetVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("retarget"));

    private sealed record Bone(string Key, string? Parent, Quat Local, V3 Offset);

    private sealed record PoseInput(List<Bone> Bones, Quat Armature, JsonObject? Soles, List<string> Omit);

    private static Quat Rotation(JsonNode? turns)
    {
        var q = Quat.Identity;
        if (turns is not JsonArray list) return q;
        foreach (var t in list)
        {
            var a = (JsonArray)t!;
            var axis = Str(a[0]) switch
            {
                "x" => new V3(1, 0, 0), "y" => new V3(0, 1, 0), "z" => new V3(0, 0, 1),
                var s => throw new ArgumentException($"unknown axis {s}"),
            };
            q *= Quat.FromAxisAngle(axis, VectorCompare.Num(a[1]) * Math.PI / 180);
        }
        return q;
    }

    private static V3 Vec(JsonNode? n)
        => n is JsonArray a && a.Count == 3 ? new V3(VectorCompare.Num(a[0]), VectorCompare.Num(a[1]), VectorCompare.Num(a[2]))
           : n is null ? V3.Zero : throw new ArgumentException($"expected [x,y,z], got {VectorCompare.Show(n)}");

    private static PoseInput Input(JsonNode? data)
    {
        var o = (JsonObject)data!;
        var bones = ((JsonArray)o["bones"]!).Select(r =>
        {
            var row = (JsonArray)r!;
            return new Bone(Str(row[0]), StrOrNull(row[1]), Rotation(row.Count > 2 ? row[2] : null), Vec(row.Count > 3 ? row[3] : null));
        }).ToList();
        var omit = o["omitPositions"] is JsonArray om ? om.Select(Str).ToList() : new List<string>();
        return new PoseInput(bones, Rotation(o["armature"]), o["soles"] as JsonObject, omit);
    }

    /// <summary>The input rest pose (<c>pose(data)</c> of the dispatch helper); matrices are rigid (R, T) pairs.</summary>
    private static RestPoseData Pose(PoseInput p)
    {
        var pose = new RestPoseData { Soles = new Dictionary<string, Sole>() };
        var frames = new Dictionary<string, (Quat R, V3 T)>();
        foreach (var b in p.Bones)
        {
            var above = b.Parent is null ? (p.Armature, V3.Zero) : frames[b.Parent];
            var here = (above.Item1 * b.Local, above.Item2 + above.Item1.Rotate(b.Offset));
            frames[b.Key] = here;
            pose.Add(b.Key, here.Item1, above.Item1, b.Parent, here.Item2);
        }
        var root = pose.RootBone;
        Quat? inverse = root is null ? null : pose.World[root].Inverse();
        foreach (var (side, points) in p.Soles ?? new JsonObject())
        {
            var foot = frames[side + "foot"];
            V3 Point(JsonNode? xyz)
            {
                var v = foot.T + foot.R.Rotate(Vec(xyz));
                return inverse is { } q ? q.Rotate(v) : v;
            }
            pose.Soles[side] = new Sole(Point(points!["heel"]), Point(points["toe"]));
        }
        foreach (var key in p.Omit) pose.Position.Remove(key);
        return pose;
    }

    private static Dictionary<string, RestFix> Corrections(PoseInput d, PoseInput t) => RestCorrections.Build(Pose(d), Pose(t));

    private static Quat Drive(Dictionary<string, RestFix> map, string key, Quat q)
        => map.TryGetValue(key, out var k) ? RestCorrections.Apply(k, q) : q;

    private static JsonArray Arr(Quat q) => new(q.X, q.Y, q.Z, q.W);
    private static JsonArray Arr(V3 v) => new(v.X, v.Y, v.Z);
    private static JsonArray Arr(IEnumerable<double> v) => new(v.Select(x => (JsonNode?)x).ToArray());

    private static Quat Animated(JsonNode? animated, string key) => Rotation(animated is JsonObject o ? o[key] : null);

    private static readonly Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch = new()
    {
        ["retargetFactors"] = a =>
        {
            var map = Corrections(Input(Arity(a, 2, 2)[0]), Input(a[1]));
            var o = new JsonObject();
            foreach (var (k, f) in map) o[k] = new JsonObject { ["left"] = Arr(f.Left), ["right"] = Arr(f.Right) };
            return o;
        },
        ["retargetKeys"] = a =>
        {
            var t = Input(Arity(a, 2, 2)[1]);
            var map = Corrections(Input(a[0]), t);
            return new JsonArray(Pose(t).Order.Where(map.ContainsKey).Select(k => (JsonNode?)k).ToArray());
        },
        ["retargetHas"] = a => Corrections(Input(Arity(a, 3, 3)[0]), Input(a[1])).ContainsKey(Str(a[2])),
        ["retargetDrive"] = a => Arr(Drive(Corrections(Input(Arity(a, 4, 4)[0]), Input(a[1])), Str(a[2]), Rotation(a[3]))),
        ["retargetDeformation"] = a =>
        {
            var t = Input(Arity(a, 4, 4)[1]);
            var key = Str(a[2]);
            return Arr(Drive(Corrections(Input(a[0]), t), key, Rotation(a[3])) * Pose(t).World[key].Inverse());
        },
        ["retargetWorld"] = a =>
        {
            var t = Input(Arity(a, 3, 3)[1]);
            var map = Corrections(Input(a[0]), t);
            var world = new Dictionary<string, Quat>();
            var o = new JsonObject();
            foreach (var b in t.Bones)
            {
                var above = b.Parent is null ? t.Armature : world[b.Parent];
                world[b.Key] = above * Drive(map, b.Key, Animated(a[2], b.Key));
                o[b.Key] = Arr(world[b.Key]);
            }
            return o;
        },
        ["retargetConstantDeformations"] = a =>
        {
            var d = Input(Arity(a, 3, 3)[0]);
            var t = Input(a[1]);
            var dp = Pose(d);
            var tp = Pose(t);
            var map = RestCorrections.Build(dp, tp);
            var dw = new Dictionary<string, Quat>();
            var tw = new Dictionary<string, Quat>();
            var o = new JsonObject();
            foreach (var b in t.Bones)
            {
                var c = Animated(a[2], b.Key);
                var dq = (b.Parent is null ? d.Armature : dw[b.Parent]) * c;
                var tq = (b.Parent is null ? t.Armature : tw[b.Parent]) * Drive(map, b.Key, c);
                dw[b.Key] = dq;
                tw[b.Key] = tq;
                var donorDef = dq * dp.World[b.Key].Inverse();
                var targetDef = tq * tp.World[b.Key].Inverse();
                o[b.Key] = Arr(donorDef.Inverse() * targetDef);
            }
            return o;
        },
        ["retargetPositions"] = a =>
        {
            var t = Input(Arity(a, 2, 3)[1]);
            var map = Corrections(Input(a[0]), t);
            var frames = new Dictionary<string, (Quat R, V3 T)>();
            var o = new JsonObject();
            foreach (var b in t.Bones)
            {
                var above = b.Parent is null ? (t.Armature, V3.Zero) : frames[b.Parent];
                var r = above.Item1 * Drive(map, b.Key, Animated(Arg(a, 2), b.Key));
                frames[b.Key] = (r, above.Item2 + above.Item1.Rotate(b.Offset));
                o[b.Key] = Arr(frames[b.Key].T);
            }
            return o;
        },
        ["retargetSoleDeltas"] = a =>
        {
            var t = Input(Arity(a, 2, 2)[1]);
            var map = Corrections(Input(a[0]), t);
            var rest = Pose(t);
            var rootQ = rest.RootBone is { } r ? rest.World[r] : Quat.Identity;
            return Arr(new[] { "left", "right" }.Select(side =>
            {
                var key = side + "foot";
                var sole = rest.Soles![side];
                var q = rootQ.Inverse() * rest.World[key];
                var k = map.TryGetValue(key, out var f) ? f.Right : Quat.Identity;
                return k.Rotate(q.Inverse().Rotate(sole.Heel - sole.Toe)).Y;
            }));
        },
        ["bindRelativeValues"] = a =>
        {
            var map = Corrections(Input(Arity(a, 4, 4)[0]), Input(a[1]));
            RestFix? k = map.TryGetValue(Str(a[2]), out var f) ? f : null;
            var values = RestCorrections.BindRelativeValues(Rotation(a[3]).ToArray(), k);
            return values is null ? null : Arr(values.Select(v => (double)v));
        },
        ["bindRelativeClipSummary"] = a =>
        {
            var map = Corrections(Input(Arity(a, 5, 5)[0]), Input(a[1]));
            var q = Rotation(a[3]).ToArray().Select(v => (float)v).ToArray();
            var pt = new ClipTrack("hips.position", new float[] { 0, 1 }, ((JsonArray)a[4]!).Select(v => (float)VectorCompare.Num(v)).ToArray());
            var clip = new List<ClipTrack> { new(Str(a[2]) + ".quaternion", new float[] { 0, 1 }, q.Concat(q).ToArray()), pt };
            var output = RestCorrections.BindRelativeClip(clip, map);
            return new JsonObject
            {
                ["sameClip"] = ReferenceEquals(output, clip),
                ["samePosition"] = ReferenceEquals(output[1], pt),
                ["positions"] = Arr(output[1].Values.Select(v => (double)v)),
                ["quaternion"] = Arr(output[0].Values.Take(4).Select(v => (double)v)),
            };
        },
        ["retargetCounterProbe"] = a =>
        {
            Quat Ry(double d) => Quat.FromAxisAngle(new V3(0, 1, 0), d * Math.PI / 180);
            Quat Rx(double d) => Quat.FromAxisAngle(new V3(1, 0, 0), d * Math.PI / 180);
            var q = Str(Arity(a, 1, 1)[0]) == "order"
                ? Rx(40).Inverse() * Ry(50) * Rx(40) * Ry(-50)
                : Ry(20) * Rx(40) * Ry(-20) * Rx(-40);
            return RestCorrections.AngleOf(q);
        },
    };

    public static TheoryData<string> Cases => VectorFile.Labels("retarget");

    [Theory]
    [MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, Dispatch);

    [Fact]
    public void EveryFunctionIsDispatched() => Assert.Empty(File.Value.MissingFunctions(Dispatch));

    [Fact]
    public void AllFiftyFiveCasesAreConsumed() => Assert.Equal(55, File.Value.Cases.Count);
}
