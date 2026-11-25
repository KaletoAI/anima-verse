using System;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using AnimaNative.Figures;
using AnimaNative.Tests.Vectors;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>
/// shared/test-vectors/role_turn.json against <see cref="RoleTurn"/> (hand derivations:
/// scripts/smoke_role_turn_vectors.mjs), plus the listing parse of <c>orientation.role_turn_deg</c>.
/// <code>
///   TS fn            C#                                   shape translation
///   roleTurnFix      RoleTurn.RoleTurnFix                 frame [9] ↔ double[]; {shift, turn} ↔ PairFix
///   turnMatrix       RoleTurn.TurnMatrix                  [3] ↔ V3, [9] ↔ double[]
///   matrixTurn       RoleTurn.MatrixTurn                  [9] ↔ double[], [3] ↔ V3
///   fixPivot         RoleTurn.FixPivot                    [3] ↔ V3
///   fixRoot          RoleTurn.FixRoot                     {position, quaternion [x,y,z,w]} ↔ (V3, Quat)
///   roleTurnPlaced   RoleTurnDeg.Parse + YawFrame + FixPivot + Fix + FixRoot   FigureManager.TickPair's chain
/// </code>
/// </summary>
public class RoleTurnVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("role_turn"));

    private static double N(JsonNode? n) => VectorCompare.Num(n);
    private static double[] Arr(JsonNode? n) => n!.AsArray().Select(N).ToArray();
    private static V3 V(JsonNode? n) { var a = Arr(n); return new V3(a[0], a[1], a[2]); }
    private static JsonArray Out(V3 v) => new(v.X, v.Y, v.Z);
    private static JsonArray Out(double[] m) => new(m.Select(x => (JsonNode?)x).ToArray());
    private static JsonObject Out(PairFix f) => new() { ["shift"] = Out(f.Shift), ["turn"] = Out(f.Turn) };
    private static JsonObject Out((V3 Position, Quat Rotation) r)
        => new() { ["position"] = Out(r.Position), ["quaternion"] = new JsonArray(r.Rotation.X, r.Rotation.Y, r.Rotation.Z, r.Rotation.W) };
    private static JsonArray Arity(JsonArray a, int n) => a.Count == n ? a : throw new ArgumentException($"expected {n} args, got {a.Count}");

    private static readonly System.Collections.Generic.Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch = new()
    {
        ["roleTurnFix"] = a => Out(RoleTurn.RoleTurnFix(N(Arity(a, 4)[0]), N(a[1]), Arr(a[2]), N(a[3]))),
        ["turnMatrix"] = a => Out(RoleTurn.TurnMatrix(V(Arity(a, 1)[0]))),
        ["matrixTurn"] = a => Out(RoleTurn.MatrixTurn(Arr(Arity(a, 1)[0]))),
        ["fixPivot"] = a => Out(RoleTurn.FixPivot(V(Arity(a, 3)[0]), Arr(a[1]), V(a[2]))),
        ["fixRoot"] = a =>
        {
            var fix = Arity(a, 3)[0]!;
            return Out(RoleTurn.FixRoot(new PairFix(V(fix["shift"]), V(fix["turn"])), V(a[1]), V(a[2])));
        },
        ["roleTurnPlaced"] = a =>
        {
            using var map = JsonDocument.Parse(Arity(a, 5)[0]!.ToJsonString());
            var turn = RoleTurnDeg.Parse(map.RootElement, a[1]!.GetValue<string>());
            var root = V(a[2]);
            var frame = RoleTurn.YawFrame(N(a[3]) * Math.PI / 180);
            var pivot = RoleTurn.FixPivot(root, frame, V(a[4]));
            return Out(RoleTurn.FixRoot(RoleTurn.Fix(turn, frame), pivot, root));
        },
    };

    public static TheoryData<string> Cases => VectorFile.Labels("role_turn");

    [Theory]
    [MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, Dispatch);

    [Fact]
    public void EveryFunctionIsDispatched() => Assert.Empty(File.Value.MissingFunctions(Dispatch));

    [Fact]
    public void AllCasesAreConsumed() => Assert.Equal(19, File.Value.Cases.Count);

    /// <summary>The listing's <c>orientation.role_turn_deg</c> reaches each entry as ITS OWN role's turn; absent or malformed = none.</summary>
    [Fact]
    public void ListingCarriesTheOwnRolesTurn()
    {
        using var listing = JsonDocument.Parse("""
            {"clips":[
              {"kind":"hug","role":"a","set":"","url":"/a.fbx","orientation":{"role_turn_deg":{"b":[10,-5,30],"c":[0,90,0]}}},
              {"kind":"hug","role":"b","set":"","url":"/b.fbx","orientation":{"role_turn_deg":{"b":[10,-5,30],"c":[0,90,0]}}},
              {"kind":"hug","role":"c","set":"","url":"/c.fbx","orientation":{"shift_cm":[1,2],"role_turn_deg":{"b":[10,-5,30],"c":[0,90,0]}}},
              {"kind":"wave","role":"b","set":"","url":"/w.fbx","orientation":{"shift_cm":[1,2]}},
              {"kind":"bad","role":"b","set":"","url":"/x.fbx","orientation":{"role_turn_deg":{"b":[10,-5]}}},
              {"kind":"bad2","role":"b","set":"","url":"/y.fbx","orientation":{"role_turn_deg":{"b":[10,"5",0]}}},
              {"kind":"bad3","role":"b","set":"","url":"/z.fbx","orientation":{"role_turn_deg":[[10,5,0]]}},
              {"kind":"bad4","role":"b","set":"","url":"/v.fbx","orientation":{"role_turn_deg":null}},
              {"kind":"idle","set":"","url":"/i.fbx","orientation":{"role_turn_deg":{"b":[10,-5,30]}}}]}
            """);
        var e = ClipLibraryRules.ParseEntries(listing.RootElement);
        Assert.Equal(RoleTurnDeg.None, e[0].RoleTurn);                    // role a: absent from the map
        Assert.Equal(new RoleTurnDeg(10, -5, 30), e[1].RoleTurn);
        Assert.Equal(new RoleTurnDeg(0, 90, 0), e[2].RoleTurn);           // a group role
        Assert.Equal(new ClipShift(1, 2), e[2].HeightOffsets.Shift);      // the shift is read beside it
        Assert.Equal(RoleTurnDeg.None, e[3].RoleTurn);                    // no role_turn_deg at all
        Assert.All(e.Skip(4), x => Assert.Equal(RoleTurnDeg.None, x.RoleTurn));   // malformed, and a solo clip
        Assert.True(e[3].RoleTurn.IsZero);
    }
}
