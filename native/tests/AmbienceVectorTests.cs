using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json.Nodes;
using AnimaNative.Scatter;
using AnimaNative.Scene;
using AnimaNative.Tests.Vectors;
using AnimaNative.World;
using Xunit;
using static AnimaNative.Tests.SceneVectorAdapters;
using static AnimaNative.Tests.ScatterVectorAdapters;

namespace AnimaNative.Tests;

/// <summary>
/// shared/test-vectors/ambience.json against <see cref="Ambience"/> (hand derivations and wrappers:
/// client3d/scripts/smoke_ambience.mjs; TS sources client3d/src/scene/ambience.ts, client3d/src/game/roomAt.ts).
///
/// <code>
///   TS fn              C#                          shape translation
///   ambienceTarget     Ambience.Target             the argument goes through the payload parser as rooms[].ambience
///   stepAmbience       Ambience.Step               {daylight, tint:[r,g,b]} ↔ AmbienceState
///   stepAmbienceN      Ambience.Step × n           (smoke wrapper)
///   nightFactorAt      Ambience.NightFactorAt
///   roomRectOf         Ambience.RoomRectOf         [[x, z], …] → P2; {x, z, w, d} | null
///   roomAtRects        Ambience.RoomAtRects        [[id, rect], …] → key/value pairs in order
///   corridorAtOutline  Ambience.CorridorAtOutline  {roomId, level, outline} → SceneCorridor
///   worldToTile        SceneView.WorldToTile       {center:{x, z}, yaw} → TileFrame
/// </code>
/// </summary>
public class AmbienceVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("ambience"));

    private static AmbienceState State(JsonNode? n)
    {
        var t = VectorCompare.NumList(Key(n, "tint")).ToArray();
        return new AmbienceState(Num(Key(n, "daylight")), t[0], t[1], t[2]);
    }

    private static JsonObject Json(AmbienceState s) => new() { ["daylight"] = s.Daylight, ["tint"] = new JsonArray(s.R, s.G, s.B) };

    private static RoomRect Rect(JsonNode? n) => new(Num(Key(n, "x")), Num(Key(n, "z")), Num(Key(n, "w")), Num(Key(n, "d")));

    private static readonly Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch = new()
    {
        ["ambienceTarget"] = a =>
        {
            Arity(a, 0, 1);
            var amb = Arg(a, 0) is { } o ? SceneJson.Ambience(Element(new JsonObject { ["ambience"] = o.DeepClone() })) : null;
            return Json(Ambience.Target(amb));
        },
        ["stepAmbience"] = a => Json(Ambience.Step(State(Arity(a, 3, 3)[0]), State(a[1]), Num(a[2]))),
        ["stepAmbienceN"] = a =>
        {
            var cur = State(Arity(a, 4, 4)[0]);
            for (int i = 0; i < Int(a[3]); i++) cur = Ambience.Step(cur, State(a[1]), Num(a[2]));
            return Json(cur);
        },
        ["nightFactorAt"] = a => Ambience.NightFactorAt(Num(Arity(a, 1, 1)[0])),
        ["roomRectOf"] = a => Ambience.RoomRectOf(Ring(Arity(a, 1, 1)[0])) is { } r
            ? new JsonObject { ["x"] = r.X, ["z"] = r.Z, ["w"] = r.W, ["d"] = r.D } : null,
        ["roomAtRects"] = a =>
        {
            var rects = ((JsonArray)Arity(a, 3, 3)[0]!).Select(p => new KeyValuePair<string, RoomRect>(Str(((JsonArray)p!)[0]), Rect(((JsonArray)p!)[1]))).ToList();
            return Ambience.RoomAtRects(rects, Num(a[1]), Num(a[2]));
        },
        ["worldToTile"] = a =>
        {
            var t = Arity(a, 3, 3)[0];
            var frame = new TileFrame(new Overview.Vec3(Num(Key(Key(t, "center"), "x")), 0, Num(Key(Key(t, "center"), "z"))), Num(Key(t, "yaw")));
            var p = SceneView.WorldToTile(frame, Num(a[1]), Num(a[2]));
            return new JsonObject { ["x"] = p.X, ["z"] = p.Z };
        },
        ["corridorAtOutline"] = a =>
        {
            var cs = ((JsonArray)Arity(a, 3, 3)[0]!).Select(c => new SceneCorridor(Str(Key(c, "roomId")), Int(Key(c, "level")),
                new P2(0, 0), Ring(Key(c, "outline")).ToArray())).ToList();
            return Ambience.CorridorAtOutline(cs, Num(a[1]), Num(a[2]));
        },
    };

    public static TheoryData<string> Cases => VectorFile.Labels("ambience");

    [Theory]
    [MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, Dispatch);

    [Fact]
    public void EveryFunctionIsDispatched() => Assert.Empty(File.Value.MissingFunctions(Dispatch));
}
