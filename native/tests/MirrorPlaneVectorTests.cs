using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json.Nodes;
using AnimaNative.Scene;
using AnimaNative.Tests.Vectors;
using Xunit;
using static AnimaNative.Tests.SceneVectorAdapters;
using static AnimaNative.Tests.ScatterVectorAdapters;

namespace AnimaNative.Tests;

/// <summary>
/// shared/test-vectors/mirror_plane.json against <see cref="MirrorMath"/> and <see cref="MirrorBudget"/> (hand
/// derivations and wrappers: scripts/smoke_mirror_plane.mjs; TS source packages/scene-render/src/mirrorSurface.ts).
///
/// <code>
///   TS fn              C#                         shape translation
///   planeOfFaces       MirrorMath.PlaneOfFaces    index null = non-indexed; {point, normal} | null
///   planeOfSquareMix   PlaneOfFaces on [9]'s square, n ccw + m cw copies (smoke wrapper)
///   mirrorBudgetRun    MirrorBudget               max null = ∞; steps [names…] | {forget}; askFrame's counter (smoke wrapper)
///   mirrorRefreshes    MirrorMath.MirrorRefreshes max null = ∞
///   mirrorPreset       MirrorMath.Preset*
/// </code>
/// </summary>
public class MirrorPlaneVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("mirror_plane"));

    private static JsonNode? PlaneJson(MirrorPlane? p)
        => p is { } q ? new JsonObject { ["point"] = Arr(q.Point), ["normal"] = Arr(q.Normal) } : null;

    private static readonly double[] Square = { 0, 0, 0, 1, 0, 0, 1, 1, 0, 0, 1, 0 };
    private static readonly int[] Ccw = { 0, 1, 2, 0, 2, 3 };
    private static readonly int[] Cw = { 0, 2, 1, 0, 3, 2 };

    private static readonly Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch = new()
    {
        ["planeOfFaces"] = a =>
        {
            Arity(a, 3, 3);
            var pos = VectorCompare.NumList(a[0]).ToList();
            List<int>? idx = a[1] is null ? null : ((JsonArray)a[1]!).Select(Int).ToList();
            var ranges = ((JsonArray)a[2]!).Select(r => (Int(((JsonArray)r!)[0]), Int(((JsonArray)r!)[1]))).ToList();
            return PlaneJson(MirrorMath.PlaneOfFaces(pos, idx, ranges));
        },
        ["planeOfSquareMix"] = a =>
        {
            int n = Int(Arity(a, 2, 2)[0]), m = Int(a[1]);
            var idx = Enumerable.Repeat(Ccw, n).SelectMany(x => x).Concat(Enumerable.Repeat(Cw, m).SelectMany(x => x)).ToList();
            return PlaneJson(MirrorMath.PlaneOfFaces(Square, idx, new[] { (0, idx.Count) }));
        },
        ["mirrorBudgetRun"] = a =>
        {
            Arity(a, 3, 3);
            var budget = new MirrorBudget(a[0] is null ? double.PositiveInfinity : Num(a[0]));
            var panes = new Dictionary<string, object>();
            object Pane(string name) => panes.TryGetValue(name, out var p) ? p : panes[name] = new object();
            var output = new JsonArray();
            double at = Num(a[1]);
            foreach (var step in (JsonArray)a[2]!)
            {
                if (step is JsonArray names)
                {
                    double frame = at;
                    var got = new JsonArray();
                    foreach (var name in names)
                    {
                        bool ok = budget.Allow(frame, Pane(Str(name)));
                        if (ok) frame += 1;
                        got.Add(ok);
                    }
                    output.Add(got);
                    at = frame + 1;
                }
                else budget.Forget(Pane(Str(Key(step, "forget"))));
            }
            return output;
        },
        ["mirrorRefreshes"] = a => MirrorMath.MirrorRefreshes(Bool(Arity(a, 3, 3)[0]), Num(a[1]),
                                                              a[2] is null ? double.PositiveInfinity : Num(a[2])),
        ["mirrorPreset"] = a =>
        {
            Arity(a, 0, 0);
            return new JsonObject
            {
                ["tint"] = MirrorMath.PresetTint, ["textureSize"] = MirrorMath.PresetTextureSize, ["clipBias"] = MirrorMath.PresetClipBias,
            };
        },
    };

    public static TheoryData<string> Cases => VectorFile.Labels("mirror_plane");

    [Theory]
    [MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, Dispatch);

    [Fact]
    public void EveryFunctionIsDispatched() => Assert.Empty(File.Value.MissingFunctions(Dispatch));
}
