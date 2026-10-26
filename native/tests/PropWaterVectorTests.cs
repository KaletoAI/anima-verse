using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json.Nodes;
using AnimaNative.Tests.Vectors;
using AnimaNative.Water;
using AnimaNative.World;
using Xunit;
using static AnimaNative.Tests.ScatterVectorAdapters;
using static AnimaNative.Tests.SceneVectorAdapters;

namespace AnimaNative.Tests;

/// <summary>
/// shared/test-vectors/prop_water.json against the native prop water (hand derivations:
/// client3d/scripts/smoke_prop_water.mjs; TS sources client3d/src/scene/propWaterMath.ts, client3d/src/game/walk.ts).
///
/// <code>
///   TS fn             C#                          shape translation
///   waterRegionAt     PropWater.WaterRegionAt     specs through the native payload parser (ScenePayload.ParseModel);
///                                                 the lift is a NUMBER in the vector — like the JS loader, it becomes
///                                                 liftOf = () => lift; absent = the TS default () => 0;
///                                                 WaterHit ↔ {y, bed_y, swim_from_m} | null
///   pointInRegion     PropWater.PointInRegion     the region through the parser's water block
///   propWaterWord     WaterGates.PropWaterWord    GroundWater ↔ {movement, sink: {move, idle}, water};
///                                                 region {y, swim_from_m, groundY?} | null → WaterHit?
///   groundWaterLevel  WaterGates.GroundWaterLevel the scope word → GroundScope
///   propWaterCarry    WaterGates.PropWaterCarry   region {y} | null
/// </code>
/// </summary>
public class PropWaterVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("prop_water"));

    private static SceneWaterRegion Region(JsonNode? region)
    {
        var spec = new JsonObject { ["water"] = new JsonObject { ["regions"] = new JsonArray(region?.DeepClone()) } };
        return Spec(spec).Water.Single();
    }

    private static JsonNode? HitJson(WaterHit? h)
        => h is { } x ? new JsonObject { ["y"] = x.Y, ["bed_y"] = x.BedY, ["swim_from_m"] = x.SwimFromM } : null;

    private static GroundWater Word(JsonNode? o)
    {
        var sink = Key(o, "sink");
        return new GroundWater(Str(Key(o, "movement")), new GroundSink(Num(Key(sink, "move")), Num(Key(sink, "idle"))),
                               Key(o, "water") is { } w ? Num(w) : null);
    }

    private static JsonObject WordJson(GroundWater w) => new()
    {
        ["movement"] = w.Movement,
        ["sink"] = new JsonObject { ["move"] = w.Sink.Move, ["idle"] = w.Sink.Idle },
        ["water"] = w.Water,
    };

    /// <summary>A region argument of the walk gates: {y, swim_from_m?, groundY?} | null (the bed is not read there).</summary>
    private static WaterHit? Hit(JsonNode? o)
    {
        if (o is null) return null;
        var swim = o is JsonObject obj && obj.ContainsKey("swim_from_m") ? Num(Key(o, "swim_from_m")) : double.NaN;
        var ground = o is JsonObject g && g.ContainsKey("groundY") ? Num(Key(o, "groundY")) : (double?)null;
        return new WaterHit(Num(Key(o, "y")), double.NaN, swim) { GroundY = ground };
    }

    private static GroundScope Scope(JsonNode? n) => Str(n) switch
    {
        "wilderness" => GroundScope.Wilderness,
        "open" => GroundScope.Open,
        "built" => GroundScope.Built,
        var s => throw new ArgumentException($"unknown scope '{s}'"),
    };

    private static readonly Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch = new()
    {
        ["waterRegionAt"] = a =>
        {
            Arity(a, 3, 4);
            var specs = ((JsonArray)a[0]!).Select(Spec).ToList();
            Func<SceneModelSpec, double>? liftOf = Arg(a, 3) is { } l ? _ => Num(l) : null;
            return HitJson(PropWater.WaterRegionAt(specs, Num(a[1]), Num(a[2]), liftOf));
        },
        ["pointInRegion"] = a => PropWater.PointInRegion(Region(Arity(a, 3, 3)[0]), Num(a[1]), Num(a[2])),
        ["propWaterWord"] = a =>
        {
            Arity(a, 3, 4);
            return WordJson(WaterGates.PropWaterWord(Word(a[0]), Num(a[1]), Num(a[2]), Hit(Arg(a, 3))));
        },
        ["groundWaterLevel"] = a => WaterGates.GroundWaterLevel(Arity(a, 2, 2)[0] is { } l ? Num(l) : null, Scope(a[1])),
        ["propWaterCarry"] = a => WaterGates.PropWaterCarry(Num(Arity(a, 2, 2)[0]), Hit(a[1])),
    };

    public static TheoryData<string> Cases => VectorFile.Labels("prop_water");

    [Theory, MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, Dispatch);

    /// <summary>Every fn of the file has a C# port in the table.</summary>
    [Fact]
    public void EveryFunctionDispatched() => E3VectorAdapters.AssertAllDispatched(File.Value, Dispatch);
}
