using System;
using System.Collections.Generic;
using System.Text.Json;
using System.Text.Json.Nodes;
using AnimaNative.Overview;
using AnimaNative.Tests.Vectors;
using Xunit;
using static AnimaNative.Tests.ScatterVectorAdapters;

namespace AnimaNative.Tests;

/// <summary>
/// shared/test-vectors/poll_schedule.json against the C# port <see cref="PollSchedule"/>
/// (hand derivations: scripts/smoke_sync_client.mjs [P1]/[P2]; TS source: packages/player-ui/src/pollCore.ts).
///
/// <code>
///   TS fn             C#
///   pollIntervalMs    PollSchedule.IntervalMs
///   nextErrorFactor   PollSchedule.NextErrorFactor
/// </code>
/// </summary>
public class PollScheduleVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("poll_schedule"));

    private static readonly Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch = new()
    {
        ["pollIntervalMs"] = a => JsonValue.Create(PollSchedule.IntervalMs(
            VectorCompare.Num(Arity(a, 3, 3)[0]), VectorCompare.Num(a[1]), VectorCompare.Num(a[2]))),
        ["nextErrorFactor"] = a => JsonValue.Create(PollSchedule.NextErrorFactor(
            VectorCompare.Num(Arity(a, 2, 2)[0]), Bool(a[1]))),
    };

    private static bool Bool(JsonNode? node)
        => node is JsonValue v && v.TryGetValue(out JsonElement el) && el.ValueKind is JsonValueKind.True or JsonValueKind.False
            ? el.ValueKind == JsonValueKind.True
            : throw new ArgumentException($"expected a boolean, got {VectorCompare.Show(node)}");

    public static TheoryData<string> Cases => VectorFile.Labels("poll_schedule");

    [Theory]
    [MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, Dispatch);

    [Fact]
    public void EveryFunctionIsDispatched()
        => Assert.Empty(File.Value.MissingFunctions(Dispatch));

    [Fact]
    public void ConstantsMatchTheTsModule()
    {
        Assert.Equal(1000, PollSchedule.TickMs);
        Assert.Equal(60_000, PollSchedule.MaxBackoffMs);
        Assert.Equal(64, PollSchedule.MaxErrorFactor);
    }
}
