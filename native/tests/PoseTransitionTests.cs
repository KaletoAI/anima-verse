using System;
using System.Collections.Generic;
using System.Text.Json;
using System.Text.Json.Nodes;
using AnimaNative.Orders;
using AnimaNative.Tests.Vectors;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>
/// shared/test-vectors/pose_transition.json against <see cref="PoseTransitions"/> (hand derivations: the docstring of
/// scripts/smoke_access_auto.py, which replays the same cases through animation_clips.resolve_pose_transition).
/// <code>
///   poseTransition(listing {transitions, pose_groups}, poseKey) → {entry: EntryKind(poseKey), exit: ExitKind(poseKey)}
/// </code>
/// </summary>
public class PoseTransitionTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("pose_transition"));

    private static JsonNode? Kind(string? kind) => kind is null ? null : JsonValue.Create(kind);

    private static readonly Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch = new()
    {
        ["poseTransition"] = a =>
        {
            using var doc = JsonDocument.Parse(a[0]!.ToJsonString());
            var table = PoseTransitions.Parse(doc.RootElement);
            var pose = a[1]!.GetValue<string>();
            return new JsonObject { ["entry"] = Kind(table.EntryKind(pose)), ["exit"] = Kind(table.ExitKind(pose)) };
        },
    };

    public static TheoryData<string> Cases => VectorFile.Labels("pose_transition");

    [Theory, MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, Dispatch);

    /// <summary>A listing without the two fields is an empty table: every lookup answers null.</summary>
    [Fact]
    public void MissingFieldsAreAnEmptyTable()
    {
        using var doc = JsonDocument.Parse("{}");
        var table = PoseTransitions.Parse(doc.RootElement);
        Assert.Null(table.EntryKind("sitting"));
        Assert.Null(table.ExitKind("sitting"));
    }
}
