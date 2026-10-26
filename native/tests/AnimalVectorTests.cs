using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json.Nodes;
using AnimaNative.Figures;
using AnimaNative.Tests.Vectors;
using Xunit;
using static AnimaNative.Tests.ScatterVectorAdapters;
using static AnimaNative.Tests.SceneVectorAdapters;

namespace AnimaNative.Tests;

/// <summary>
/// The adapters of client3d/scripts/animalVectorDispatch.mjs (Task 34), mirrored for the native port (hand derivations:
/// client3d/scripts/smoke_animal_vectors.mjs):
/// <code>
///   TS fn                       C#                              shape translation
///   findLegChains               ProceduralGait.FindLegChains    {name, parent|null, position{x,y,z}} ↔ GaitBone,
///                                                               {min, max} ↔ GaitBox; chains as {bone, foot, axis[3],
///                                                               phaseWalk, phaseRun}
///   advanceProceduralPhase      ProceduralGait.AdvancePhase     gait "walk" | "run" | null
///   proceduralGaitAmplitudes    ProceduralGait.GaitAmplitudes   {swing, bob}
///   proceduralIdleAmplitudes    ProceduralGait.IdleAmplitudes   {bob, scale}
/// </code>
/// </summary>
internal static class AnimalVectorAdapters
{
    private static V3 Vec(JsonNode? n) => new(Num(Key(n, "x")), Num(Key(n, "y")), Num(Key(n, "z")));

    public static List<GaitBone> Bones(JsonNode? n)
        => ((JsonArray)n!).Select(b => new GaitBone(Str(Key(b, "name")), Key(b, "parent") is { } p ? (int)Num(p) : null,
                                                    Vec(Key(b, "position")))).ToList();

    public static GaitBox Box(JsonNode? n) => new(Vec(Key(n, "min")), Vec(Key(n, "max")));

    public static JsonArray Chains(IEnumerable<GaitChain> chains)
        => new(chains.Select(c => (JsonNode)new JsonObject
        {
            ["bone"] = c.Bone, ["foot"] = c.Foot, ["axis"] = new JsonArray(c.Axis.X, c.Axis.Y, c.Axis.Z),
            ["phaseWalk"] = c.PhaseWalk, ["phaseRun"] = c.PhaseRun,
        }).ToArray());

    public static readonly Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch = new()
    {
        ["findLegChains"] = a => Chains(ProceduralGait.FindLegChains(Bones(a[0]), Box(a[1]))),
        ["advanceProceduralPhase"] = a => ProceduralGait.AdvancePhase(Num(a[0]), Num(a[1]), StrOrNull(a[2])),
        ["proceduralGaitAmplitudes"] = a =>
        {
            var (swing, bob) = ProceduralGait.GaitAmplitudes(Num(a[0]), Num(a[1]), Num(a[2]));
            return new JsonObject { ["swing"] = swing, ["bob"] = bob };
        },
        ["proceduralIdleAmplitudes"] = a =>
        {
            var (bob, scale) = ProceduralGait.IdleAmplitudes(Num(a[0]));
            return new JsonObject { ["bob"] = bob, ["scale"] = scale };
        },
    };
}

public class AnimalLegsVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("animal_legs"));
    public static TheoryData<string> Cases => VectorFile.Labels("animal_legs");

    [Theory]
    [MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, AnimalVectorAdapters.Dispatch);

    [Fact]
    public void EveryFunctionIsDispatched() => Assert.Empty(File.Value.MissingFunctions(AnimalVectorAdapters.Dispatch));
}

public class AnimalGaitVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("animal_gait"));
    public static TheoryData<string> Cases => VectorFile.Labels("animal_gait");

    [Theory]
    [MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, AnimalVectorAdapters.Dispatch);

    [Fact]
    public void EveryFunctionIsDispatched() => Assert.Empty(File.Value.MissingFunctions(AnimalVectorAdapters.Dispatch));
}
