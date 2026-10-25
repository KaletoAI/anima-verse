using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using AnimaNative.Overview;
using AnimaNative.Tests.Vectors;
using Xunit;
using static AnimaNative.Tests.ScatterVectorAdapters;

namespace AnimaNative.Tests;

/// <summary>
/// shared/test-vectors/overview_labels.json against <see cref="OverviewLabels"/> and <see cref="OpenView"/>
/// (hand derivations: client3d/scripts/smoke_overview_labels.mjs; TS sources client3d/src/scene/nameTags.ts and
/// client3d/src/game/openView.ts).
///
/// <code>
///   TS fn                C#                               shape translation
///   tagVisible           OverviewLabels.TagVisible
///   tagTravelling        OverviewLabels.TagTravelling     travel {starts_in_s?, eta_hhmm?} | null → TagTravel?
///   tagName              OverviewLabels.TagName           (same)
///   tagAnchorY           OverviewLabels.TagAnchorY        null = a portrait → double? null
///   locationLabelLift    OverviewLabels.LocationLabelLift
///   closeTargetDist      OpenView.CloseTargetDist
///   openViewShouldClose  OpenView.ShouldClose
/// </code>
/// The travel block goes through the PAYLOAD parser (<see cref="TagTravel.FromJson"/>) — the one the client runs on
/// a world-map row — so the vectors pin the JS truthiness of <c>starts_in_s</c> / <c>eta_hhmm</c> there too.
/// </summary>
public class OverviewLabelsVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("overview_labels"));

    private static readonly Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch = new()
    {
        ["tagVisible"] = a => JsonValue.Create(OverviewLabels.TagVisible(
            VectorCompare.Num(Arity(a, 3, 3)[0]), Bool(a[1]), Bool(a[2]))),
        ["tagTravelling"] = a => JsonValue.Create(OverviewLabels.TagTravelling(Travel(Arity(a, 1, 1)[0]))),
        ["tagName"] = a => JsonValue.Create(OverviewLabels.TagName(Str(Arity(a, 2, 2)[0]), Travel(a[1]))),
        ["tagAnchorY"] = a => JsonValue.Create(OverviewLabels.TagAnchorY(
            Arity(a, 1, 1)[0] is null ? null : VectorCompare.Num(a[0]))),
        ["locationLabelLift"] = a => JsonValue.Create(OverviewLabels.LocationLabelLift(VectorCompare.Num(Arity(a, 1, 1)[0]))),
        ["closeTargetDist"] = a => JsonValue.Create(OpenView.CloseTargetDist(VectorCompare.Num(Arity(a, 1, 1)[0]))),
        ["openViewShouldClose"] = a =>
        {
            var n = Arity(a, 6, 6).Select(VectorCompare.Num).ToArray();
            return JsonValue.Create(OpenView.ShouldClose(n[0], n[1], n[2], n[3], n[4], n[5]));
        },
    };

    /// <summary>A travel block as the map row carries it: <c>{"travel": …}</c> through the payload parser.</summary>
    private static TagTravel? Travel(JsonNode? node)
    {
        if (node is not null && node is not JsonObject)
            throw new ArgumentException($"expected a travel object or null, got {VectorCompare.Show(node)}");
        var row = new JsonObject { ["name"] = "x", ["travel"] = node?.DeepClone() };
        return TagTravel.FromJson(JsonSerializer.SerializeToElement(row));
    }

    private static bool Bool(JsonNode? node)
        => node is JsonValue v && v.TryGetValue(out JsonElement el) && el.ValueKind is JsonValueKind.True or JsonValueKind.False
            ? el.ValueKind == JsonValueKind.True
            : throw new ArgumentException($"expected a boolean, got {VectorCompare.Show(node)}");

    public static TheoryData<string> Cases => VectorFile.Labels("overview_labels");

    [Theory]
    [MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, Dispatch);

    [Fact]
    public void EveryFunctionIsDispatched() => Assert.Empty(File.Value.MissingFunctions(Dispatch));

    [Fact]
    public void ConstantsMatchTheTsModules()
    {
        Assert.Equal(55, OverviewLabels.TagMaxCamDist);
        Assert.Equal(0.45, OverviewLabels.TagAboveHeadM);
        Assert.Equal(-0.15, OverviewLabels.TagPortraitY);
        Assert.Equal(2.2, OverviewLabels.LocationLabelLiftM);
        Assert.Equal(60, OpenView.CloseCamDist);
        Assert.Equal(3, OpenView.CloseTargetFootprints);
        Assert.Equal(12, OpenView.CloseTargetMinM);
    }
}

/// <summary>
/// shared/test-vectors/event_pins.json against <see cref="EventPinRule"/> (hand derivations:
/// client3d/scripts/smoke_event_pins.mjs; TS source client3d/src/game/eventPins.ts).
/// <code>
///   TS fn      C#                      shape translation
///   pinGlyph   EventPinRule.PinGlyph   events [{category}] | null → the categories (a non-string or absent
///                                      category → null, which never equals 'danger'); null → null
///   pinY       EventPinRule.PinY
/// </code>
/// </summary>
public class EventPinsVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("event_pins"));

    private static readonly Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch = new()
    {
        ["pinGlyph"] = a => JsonValue.Create(EventPinRule.PinGlyph(Categories(Arity(a, 1, 1)[0]))),
        ["pinY"] = a => JsonValue.Create(EventPinRule.PinY(VectorCompare.Num(Arity(a, 2, 2)[0]), VectorCompare.Num(a[1]))),
    };

    private static IReadOnlyCollection<string?>? Categories(JsonNode? node)
    {
        if (node is null) return null;
        if (node is not JsonArray list) throw new ArgumentException($"expected an event list or null, got {VectorCompare.Show(node)}");
        return list.Select(e => e is JsonObject o && o["category"] is JsonValue v && v.TryGetValue<string>(out var s) ? s : null)
                   .ToList();
    }

    public static TheoryData<string> Cases => VectorFile.Labels("event_pins");

    [Theory]
    [MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, Dispatch);

    [Fact]
    public void EveryFunctionIsDispatched() => Assert.Empty(File.Value.MissingFunctions(Dispatch));

    [Fact]
    public void LiftMatchesTheTsModule() => Assert.Equal(3.5, EventPinRule.LiftM);
}
