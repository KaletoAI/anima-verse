using System;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using System.Text.Json.Serialization;
using AnimaNative.Figures;
using AnimaNative.Tests.Vectors;
using Xunit;
using static AnimaNative.Tests.ScatterVectorAdapters;

namespace AnimaNative.Tests;

/// <summary>
/// shared/test-vectors/pair_scale.json against <see cref="PairScale"/> (hand derivations: scripts/smoke_pair_scale.mjs,
/// [8] = the browser scene's deleted smoke_pair_root_sets.mjs [B] as the pure composition).
/// <code>
///   TS fn              C#                                          shape translation
///   pairFigureScale    PairScale.FigureScale                       height: number | null | undefined (= null) | NaN
///   pairPivotOf        PairScale.PivotOf                           the stored value as a JsonElement (undefined = default;
///                                                                  NaN serialised as the string "NaN": rejected either way)
///   scalePairRoot      PairScale.ScaleRoot                         {x, z} ↔ (X, Z), pivot {x, z} ↔ PairXZ
///   scalePairShift     PairScale.ScaleShift                        {x, z} ↔ (X, Z)
///   pairContactPoint   PivotOf + FigureScale + ScaleRoot           (p, pivot cm, height) → p' + a·(C − p), the body-fixed
///                                                                  contact point after scaling (= C)
///   pairPlacedRoot     FigureScale + ScaleRoot + PairClip.AnchorPoint   FigureManager.TickPair's order: scale, then the anchor
///   pairAxisGap        PairHeight.AxisGap                          {root, axis, lengthM, opening} ↔ PairHeightRelationFrame
///   pairContactFrame   PairHeight.ContactFrame                     [frame | null] → index
///   pairRoleClass      PairHeight.RoleClass                        {frames: [{groundM, hipsM, legs: [{hip, knee, ankle}]}], fixed?}
///                                                                  ↔ PairHeightRole → {stance, planted, kneeHeld}
///   pairRoleRange      PairHeight.RoleRange                        the same role → {down, up, stance, planted, kneeHeld}
///   ikKnee             PairHeight.IkKnee                           [x, y, z] ↔ V3
///   pairHeightOffsets  PairHeight.Offsets                          {roles, relations: [{key, part, receiver, frames}]}
///                                                                  → {offsets, residuals, gaps, contactFrames, ranges}
/// </code>
/// </summary>
public class PairScaleVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("pair_scale"));
    private static readonly JsonSerializerOptions NamedFloats = new() { NumberHandling = JsonNumberHandling.AllowNamedFloatingPointLiterals };

    private static double N(JsonNode? n) => VectorCompare.Num(n);
    private static bool IsUndefined(JsonNode? n) => n is JsonValue v && v.TryGetValue(out JsonElement e) && e.ValueKind == JsonValueKind.Undefined;
    private static double? Height(JsonNode? n) => n is null || IsUndefined(n) ? null : N(n);
    private static (double X, double Z) Xz(JsonNode? n) => (N(n!["x"]), N(n["z"]));
    private static PairXZ Pivot(JsonNode? n) => new(N(n!["x"]), N(n["z"]));
    private static JsonObject Out((double X, double Z) p) => new() { ["x"] = p.X, ["z"] = p.Z };

    private static V3 P3(JsonNode? n) => new(N(n![0]), N(n[1]), N(n[2]));
    private static JsonArray V(V3 v) => new(v.X, v.Y, v.Z);
    private static PairHeightRoleFrame RoleFrame(JsonNode? n) => new(N(n!["groundM"]), N(n["hipsM"]),
        n["legs"]!.AsArray().Select(l => new PairLeg(P3(l!["hip"]), P3(l["knee"]), P3(l["ankle"]))).ToArray());
    private static PairHeightRole Role(JsonNode? n) => new(n!["frames"]!.AsArray().Select(RoleFrame).ToArray(),
        n["fixed"] is JsonValue f && f.GetValue<bool>());
    private static PairHeightRelationFrame? RelFrame(JsonNode? n) => n is null ? null
        : new PairHeightRelationFrame(P3(n["root"]), P3(n["axis"]), N(n["lengthM"]), P3(n["opening"]));
    private static JsonArray Bools(bool[] b) => new(b.Select(p => (JsonNode)JsonValue.Create(p)).ToArray());
    private static JsonObject ClassOut(PairRoleClass c) => new() { ["stance"] = c.Stance, ["planted"] = Bools(c.Planted), ["kneeHeld"] = Bools(c.KneeHeld) };

    private static JsonElement Element(JsonNode? n)
    {
        if (IsUndefined(n)) return default;
        return n is null ? JsonDocument.Parse("null").RootElement : JsonSerializer.SerializeToElement(n, NamedFloats);
    }

    private static readonly System.Collections.Generic.Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch = new()
    {
        ["pairFigureScale"] = a => PairScale.FigureScale(Height(Arity(a, 1, 1)[0])),
        ["pairPivotOf"] = a => { var p = PairScale.PivotOf(Element(Arity(a, 1, 1)[0])); return Out((p.X, p.Z)); },
        ["scalePairRoot"] = a => Out(PairScale.ScaleRoot(Xz(Arity(a, 3, 3)[0]), Pivot(a[1]), N(a[2]))),
        ["scalePairShift"] = a => Out(PairScale.ScaleShift(Xz(Arity(a, 2, 2)[0]), N(a[1]))),
        ["pairContactPoint"] = a =>
        {
            var p = Xz(Arity(a, 3, 3)[0]);
            var c = PairScale.PivotOf(Element(a[1]));
            double s = PairScale.FigureScale(Height(a[2]));
            var q = PairScale.ScaleRoot(p, c, s);
            return Out((q.X + s * (c.X - p.X), q.Z + s * (c.Z - p.Z)));
        },
        ["pairAxisGap"] = a => PairHeight.AxisGap(RelFrame(Arity(a, 1, 1)[0])!),
        ["pairContactFrame"] = a => PairHeight.ContactFrame(Arity(a, 1, 1)[0]!.AsArray().Select(RelFrame).ToArray()),
        ["pairRoleClass"] = a => ClassOut(PairHeight.RoleClass(Role(Arity(a, 1, 1)[0]))),
        ["pairRoleRange"] = a =>
        {
            var r = PairHeight.RoleRange(Role(Arity(a, 1, 1)[0]));
            var o = ClassOut(r);
            o["down"] = r.Down; o["up"] = r.Up;
            return o;
        },
        ["ikKnee"] = a => V(PairHeight.IkKnee(P3(Arity(a, 4, 4)[0]), P3(a[1]), P3(a[2]), P3(a[3]))),
        ["pairHeightOffsets"] = a =>
        {
            var input = Arity(a, 1, 1)[0]!;
            var roles = input["roles"]!.AsObject().ToDictionary(kv => kv.Key, kv => Role(kv.Value));
            var relations = input["relations"]!.AsArray().Select(r => new PairHeightRelation(
                r!["key"]!.GetValue<string>(), r["part"]!.GetValue<string>(), r["receiver"]!.GetValue<string>(),
                r["frames"]!.AsArray().Select(RelFrame).ToArray())).ToArray();
            var s = PairHeight.Offsets(roles, relations);
            static JsonObject Map<T>(System.Collections.Generic.Dictionary<string, T> d)
            {
                var o = new JsonObject();
                foreach (var (k, v) in d) o[k] = JsonValue.Create(v);
                return o;
            }
            var ranges = new JsonObject();
            foreach (var (k, r) in s.Ranges) { var o = ClassOut(r); o["down"] = r.Down; o["up"] = r.Up; ranges[k] = o; }
            return new JsonObject { ["offsets"] = Map(s.Offsets), ["residuals"] = Map(s.Residuals), ["gaps"] = Map(s.Gaps),
                                    ["contactFrames"] = Map(s.ContactFrames), ["ranges"] = ranges };
        },
        ["pairPlacedRoot"] = a =>
        {
            var r = PairScale.ScaleRoot(Xz(Arity(a, 4, 4)[0]), Pivot(a[1]), PairScale.FigureScale(Height(a[2])));
            var anchor = a[3]!;
            return Out(PairClip.AnchorPoint(N(anchor["x"]), N(anchor["z"]), N(anchor["yaw"]), r.X, r.Z));
        },
    };

    public static TheoryData<string> Cases => VectorFile.Labels("pair_scale");

    [Theory]
    [MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, Dispatch);

    [Fact]
    public void EveryFunctionIsDispatched() => Assert.Empty(File.Value.MissingFunctions(Dispatch));

    [Fact]
    public void AllSixtyFiveCasesAreConsumed() => Assert.Equal(65, File.Value.Cases.Count);

    /// <summary>H[7] beyond the vector: gaps inside the deadband compute no range at all (nothing is applied).</summary>
    [Fact]
    public void GapsInsideTheDeadbandComputeNothing()
    {
        var leg = new PairLeg(new V3(0.1, 0.88, 0), new V3(0.1, 0.48, 0.2), new V3(0.1, 0.08, 0));
        var role = new PairHeightRole(new[] { new PairHeightRoleFrame(0, 0.95, new[] { leg, leg }) });
        var frame = new PairHeightRelationFrame(new V3(0, 1, 0), new V3(0, 0, 1), 0.2, new V3(0, 0.996, 0.15));
        var s = PairHeight.Offsets(new System.Collections.Generic.Dictionary<string, PairHeightRole> { ["a"] = role, ["b"] = role },
            new[] { new PairHeightRelation("b>a:mouth", "b", "a", new PairHeightRelationFrame?[] { frame }) });
        Assert.Empty(s.Ranges);
        Assert.Equal(0.0, s.Gaps["b>a:mouth"]);
        Assert.All(s.Offsets.Values, v => Assert.Equal(0.0, v));
    }

    /// <summary>[3] beyond the vector: a == 1 returns the very input (no arithmetic) — the bit-identity of a 1.70 m figure.</summary>
    [Fact]
    public void ScaleOneIsBitIdentical()
    {
        var p = (0.1 + 0.2, -0.3 / 7);
        Assert.Equal(p, PairScale.ScaleRoot(p, new PairXZ(0.12, 0.3), PairScale.FigureScale(1.7)));
        Assert.Equal(p, PairScale.ScaleShift(p, PairScale.FigureScale(null)));
    }

    /// <summary>The listing's <c>pair_pivot_cm</c> reaches the clip source entry; a row without one has the origin.</summary>
    [Fact]
    public void ListingCarriesThePivot()
    {
        using var listing = JsonDocument.Parse("""
            {"clips":[{"kind":"hug","role":"a","set":"","url":"/a.fbx","pair_pivot_cm":[12,30]},
                      {"kind":"hug","role":"b","set":"","url":"/b.fbx","pair_pivot_cm":null},
                      {"kind":"idle","set":"","url":"/i.fbx"}]}
            """);
        var entries = ClipLibraryRules.ParseEntries(listing.RootElement);
        Assert.Equal(new PairXZ(0.12, 0.3), entries[0].PairPivot);
        Assert.Equal(PairScale.Origin, entries[1].PairPivot);
        Assert.Equal(PairScale.Origin, entries[2].PairPivot);
    }
}
