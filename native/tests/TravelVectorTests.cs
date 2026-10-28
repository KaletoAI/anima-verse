using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json.Nodes;
using AnimaNative.Figures;
using AnimaNative.Tests.Vectors;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>Task 42 / E6-T2: all travel.json cases, with travelVectorDispatch.mjs shapes and format /1 sentinels.</summary>
public class TravelVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("travel"));
    private static double N(JsonNode? n) => VectorCompare.TryNum(n, out var d) ? d : double.NaN;
    private static double? Rate(JsonNode? n) => n is null ? null : N(n);
    private static (double X, double Z)? Point(JsonNode? n) => n is JsonArray a ? (N(a[0]), N(a[1])) : null;
    private static List<(double X, double Z)>? Points(JsonNode? n) => n is JsonArray a ? a.Select(p => Point(p) ?? (double.NaN, double.NaN)).ToList() : null;
    private static List<double?>? Paces(JsonNode? n) => n is JsonArray a ? a.Select(Rate).ToList() : null;
    private static JsonNode? Pt((double X, double Z)? p) => p is { } v ? new JsonArray(v.X, v.Z) : null;
    private static JsonNode Pts(IEnumerable<(double X, double Z)> ps) => new JsonArray(ps.Select(p => Pt(p)).ToArray());
    private static readonly Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch = new()
    {
        ["polylineLength"] = a => TravelPath.PolylineLength(Points(a[0])),
        ["pointAtDistance"] = a => Pt(TravelPath.PointAtDistance(Points(a[0]), N(a[1]))),
        ["clampProgress"] = a => TravelPath.ClampProgress(N(a[0]), N(a[1])),
        ["catchUpStep"] = a => TravelPath.CatchUpStep(N(a[0]), Rate(a[1]), N(a[2]), N(a[3])),
        ["trimBucket"] = a => TravelPath.TrimBucket(N(a[0])),
        ["remainingPoints"] = a => Pts(TravelPath.RemainingPoints(Points(a[0]), N(a[1]))),
        ["densifyPolyline"] = a => Pts(TravelPath.DensifyPolyline(Points(a[0]), a.Count > 1 ? N(a[1]) : 4, a.Count > 2 ? N(a[2]) : 400)),
        ["advanceAlongPaces"] = a => TravelPath.AdvanceAlongPaces(Points(a[0]), Paces(a[1]), N(a[2]), N(a[3])),
        ["ageAtReceiptS"] = a => TravelPath.AgeAtReceiptS(new TravelSync(N(a[0]!["clock_age_ms"]), N(a[0]!["build_ms"])),
            new MapReceipt(N(a[1]!["polledAt"]), N(a[1]!["headersAt"]), N(a[1]!["parsedAt"]))),
        ["stepShown"] = a => TravelPath.StepShown(Points(a[0]), Paces(a[1]), N(a[2]), N(a[3]), N(a[4]), a.Count > 5 ? N(a[5]) : 1),
        ["rateAt"] = a => JsonValue.Create(TravelPath.RateAt(Points(a[0]), Paces(a[1]), N(a[2]))),
        ["hardSnapM"] = a => TravelPath.HardSnapM(Rate(a[0])),
        ["adoptTarget"] = a => { var r = TravelPath.AdoptTarget(N(a[0]), N(a[1]), Rate(a[2])); return new JsonObject { ["shownM"] = r.ShownM, ["snap"] = r.Snap }; },
        ["deadReckonRate"] = a => JsonValue.Create(TravelPath.DeadReckonRate(Point(a[0]), N(a[1]), Point(a[2]), N(a[3]))),
        ["deadReckonStep"] = a => TravelPath.DeadReckonStep(Rate(a[0]), Rate(a[1]), N(a[2]), N(a[3])),
        ["errWindowMax"] = a => { var w = new TravelPath.ErrWindow(); foreach (var s in (JsonArray)a[0]!) w.Push(N(s![0]), N(s[1])); return w.Max(N(a[1])); },
    };
    public static TheoryData<string> Cases => VectorFile.Labels("travel");
    [Theory, MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, Dispatch);
    [Fact]
    public void EveryFunctionIsDispatched() => Assert.Empty(File.Value.MissingFunctions(Dispatch));
}
