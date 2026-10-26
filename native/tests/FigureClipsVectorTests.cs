using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using AnimaNative.Figures;
using AnimaNative.Tests.Vectors;
using AnimaNative.Water;
using Xunit;
using static AnimaNative.Tests.ScatterVectorAdapters;
using static AnimaNative.Tests.SceneVectorAdapters;

namespace AnimaNative.Tests;

/// <summary>
/// shared/test-vectors/figure_clips.json against <see cref="FigureClips"/> (hand derivations:
/// client3d/scripts/smoke_figure_clips.mjs).
///
/// <code>
///   TS fn                    C#                                   TS source
///   resolveMovementPoses     FigureClips.ResolveMovementPoses     client3d game/walk.ts
///   moveClip                 FigureClips.MoveClip
///   idleClip                 FigureClips.IdleClip
///   standingClipFor          FigureClips.StandingClipFor          null animation = none (smoke wrapper: undefined)
///   movementOf               FigureClips.MovementOf
///   canRun                   FigureClips.CanRun
///   movementPoseOf           FigureClips.MovementPoseOf
///   resolveClipTransitions   FigureClips.ResolveClipTransitions
///   clipTransition           FigureClips.Transition
///   bridgePace               FigureClips.BridgePace
///   clipKindChain            FigureClips.ClipKindChain            client3d scene/clipCoverage.ts
///   resolveClipKind          FigureClips.ResolveClipKind
///   proceduralGait           FigureClips.ProceduralGait
/// </code>
/// A pose-table argument is the RESOLVED table (<c>{pose: {kind, publicKind}}</c>) and goes through
/// <see cref="PoseClips.Of"/> unchanged; the raw server payload of <c>resolveMovementPoses</c> and
/// <c>resolveClipTransitions</c> goes in as the parsed <see cref="JsonElement"/> the clip library hands over.
/// </summary>
public class FigureClipsVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("figure_clips"));

    private static JsonElement? Raw(JsonNode? node) => node is null ? null : Element(node);

    private static PoseClips Poses(JsonNode? node)
    {
        if (node is not JsonObject o) throw new ArgumentException($"expected a pose table, got {VectorCompare.Show(node)}");
        return PoseClips.Of(o.ToDictionary(kv => kv.Key, kv => new PoseClip(Str(Key(kv.Value, "kind")), Str(Key(kv.Value, "publicKind")))));
    }

    private static JsonObject PosesJson(PoseClips poses)
    {
        var o = new JsonObject();
        foreach (var (pose, e) in poses.Entries) o[pose] = new JsonObject { ["kind"] = e.Kind, ["publicKind"] = e.PublicKind };
        return o;
    }

    private static JsonObject? RuleJson(ClipTransition? r)
        => r is null ? null : new JsonObject { ["from"] = r.From, ["to"] = r.To, ["kind"] = r.Kind, ["accel"] = r.Accel };

    private static List<ClipTransition> Table(JsonNode? node)
        => ((JsonArray)node!).Select(r => new ClipTransition(Str(Key(r, "from")), Str(Key(r, "to")), Str(Key(r, "kind")),
                                                            Num(Key(r, "accel")))).ToList();

    private static List<string> Strs(JsonNode? node) => ((JsonArray)node!).Select(Str).ToList();

    private static JsonArray StrsJson(IEnumerable<string> list) => new(list.Select(s => (JsonNode?)s).ToArray());

    private static GroundScope Scope(JsonNode? n) => Str(n) switch
    {
        "wilderness" => GroundScope.Wilderness,
        "open" => GroundScope.Open,
        "built" => GroundScope.Built,
        var s => throw new ArgumentException($"unknown scope '{s}'"),
    };

    private static readonly Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch = new()
    {
        ["resolveMovementPoses"] = a => PosesJson(FigureClips.ResolveMovementPoses(Raw(Arity(a, 1, 1)[0]))),
        ["moveClip"] = a => FigureClips.MoveClip(Str(Arity(a, 3, 3)[0]), Bool(a[1]), Poses(a[2])),
        ["idleClip"] = a => FigureClips.IdleClip(Str(Arity(a, 2, 2)[0]), Poses(a[1])),
        ["standingClipFor"] = a => FigureClips.StandingClipFor(StrOrNull(Arity(a, 3, 3)[0]), StrOrNull(a[1]), Poses(a[2])),
        ["movementOf"] = a => FigureClips.MovementOf(StrOrNull(Arity(a, 2, 2)[0]), Scope(a[1])),
        ["canRun"] = a => FigureClips.CanRun(Str(Arity(a, 1, 1)[0])),
        ["movementPoseOf"] = a => FigureClips.MovementPoseOf(StrOrNull(Arity(a, 2, 2)[0]), Poses(a[1])),
        ["resolveClipTransitions"] = a => new JsonArray(FigureClips.ResolveClipTransitions(Raw(Arity(a, 1, 1)[0]))
                                                                   .Select(r => (JsonNode?)RuleJson(r)).ToArray()),
        ["clipTransition"] = a => RuleJson(FigureClips.Transition(StrOrNull(Arity(a, 3, 3)[0]), Str(a[1]), Table(a[2]))),
        ["bridgePace"] = a => FigureClips.BridgePace(Num(Arity(a, 2, 2)[0]), Num(a[1])),
        ["clipKindChain"] = a => StrsJson(FigureClips.ClipKindChain(Str(Arity(a, 2, 2)[0]), Poses(a[1]))),
        ["resolveClipKind"] = a => FigureClips.ResolveClipKind(Str(Arity(a, 3, 3)[0]), Strs(a[1]), Poses(a[2])),
        ["proceduralGait"] = a => FigureClips.ProceduralGait(StrOrNull(Arity(a, 2, 2)[0]), Poses(a[1])),
    };

    public static TheoryData<string> Cases => VectorFile.Labels("figure_clips");

    [Theory]
    [MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, Dispatch);

    [Fact]
    public void EveryFunctionIsDispatched() => Assert.Empty(File.Value.MissingFunctions(Dispatch));

    [Fact]
    public void AllSixtyFourCasesAreConsumed() => Assert.Equal(64, File.Value.Cases.Count);

    /// <summary>The resolved fixture tables are what <c>resolveMovementPoses</c> makes of the raw ones (smoke's tail).</summary>
    [Fact]
    public void FixtureTablesAgreeWithTheResolver()
    {
        var fx = File.Value.Fixtures;
        Assert.True(VectorCompare.Near(fx["POSES_SERVER"], PosesJson(FigureClips.ResolveMovementPoses(Element(fx["RAW_SERVER"]))), 0, out var d1), d1);
        Assert.True(VectorCompare.Near(fx["POSES_DEFAULT"], PosesJson(PoseClips.Default), 0, out var d2), d2);
        Assert.True(VectorCompare.Near(fx["TABLE"], new JsonArray(FigureClips.ResolveClipTransitions(Element(fx["RAW_TABLE"]))
                                                                             .Select(r => (JsonNode?)RuleJson(r)).ToArray()), 0, out var d3), d3);
    }

    /// <summary>A pose table without all seven poses is refused (the browser would throw on the missing pose).</summary>
    [Fact]
    public void IncompletePoseTableThrows()
        => Assert.Throws<ArgumentException>(() => PoseClips.Of(new Dictionary<string, PoseClip> { ["standing"] = new("idle", "idle") }));
}
