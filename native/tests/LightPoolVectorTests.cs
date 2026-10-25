using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json.Nodes;
using AnimaNative.Overview;
using AnimaNative.Scene;
using AnimaNative.Tests.Vectors;
using Xunit;
using static AnimaNative.Tests.SceneVectorAdapters;
using static AnimaNative.Tests.ScatterVectorAdapters;

namespace AnimaNative.Tests;

/// <summary>
/// shared/test-vectors/light_pool.json against <see cref="PropLights"/> (hand derivations and wrappers:
/// client3d/scripts/smoke_light_pool.mjs; TS source client3d/src/scene/lightPool.ts).
///
/// <code>
///   TS fn                 C#                               shape translation
///   pickLights            PropLights.PickLights            sources {id, pos{x,y,z}, range_m, when, room_id?}; rooms LIST → set
///   flickerFactor         PropLights.FlickerFactor
///   nightLightGain        PropLights.NightLightGain
///   haloVisible           PropLights.HaloVisible
///   fireColourMix         PropLights.FireColourMix
///   stepLightSlot         PropLights.StepLightSlot          {id, gain} ↔ LightSlotState
///   lightPositionInFrame  PropLights.LightPositionInFrame   light {offset_m:[x,z], height_m}; result [x, y, z]
///   lightPoolSize         PropLights.PoolSize
/// </code>
/// </summary>
public class LightPoolVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("light_pool"));

    private static readonly Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch = new()
    {
        ["pickLights"] = a =>
        {
            Arity(a, 6, 6);
            var sources = ((JsonArray)a[0]!).Select(s => new LightSourceView(Str(Key(s, "id")), XYZ(Key(s, "pos")),
                Num(Key(s, "range_m")), Str(Key(s, "when")), Key(s, "room_id") is { } r ? Str(r) : "")).ToList();
            var rooms = ((JsonArray)a[4]!).Select(Str).ToHashSet();
            var prev = ((JsonArray)a[5]!).Select(Str).ToList();
            var got = PropLights.PickLights(sources, XYZ(a[1]), Int(a[2]), Num(a[3]), rooms, prev);
            return new JsonArray(got.Select(id => (JsonNode?)id).ToArray());
        },
        ["flickerFactor"] = a => PropLights.FlickerFactor(Str(Arity(a, 3, 3)[0]), Num(a[1]), Num(a[2])),
        ["nightLightGain"] = a => PropLights.NightLightGain(Str(Arity(a, 2, 2)[0]), Num(a[1])),
        ["haloVisible"] = a => PropLights.HaloVisible(Bool(Arity(a, 3, 3)[0]), Str(a[1]), Num(a[2])),
        ["fireColourMix"] = a => PropLights.FireColourMix(Num(Arity(a, 2, 2)[0]), Num(a[1])),
        ["stepLightSlot"] = a =>
        {
            var s = PropLights.StepLightSlot(new LightSlotState(Str(Key(Arity(a, 3, 3)[0], "id")), Num(Key(a[0], "gain"))),
                                             Str(a[1]), Num(a[2]));
            return new JsonObject { ["id"] = s.Id, ["gain"] = s.Gain };
        },
        ["lightPositionInFrame"] = a =>
        {
            Arity(a, 4, 4);
            var frame = VectorCompare.NumList(a[0]).ToArray();
            var anchor = VectorCompare.NumList(a[1]).ToArray();
            var off = VectorCompare.NumList(Key(a[3], "offset_m")).ToArray();
            return Arr(PropLights.LightPositionInFrame(frame, anchor[0], anchor[1], Num(a[2]), off[0], off[1], Num(Key(a[3], "height_m"))));
        },
        ["lightPoolSize"] = a => { Arity(a, 0, 0); return PropLights.PoolSize; },
    };

    public static TheoryData<string> Cases => VectorFile.Labels("light_pool");

    [Theory]
    [MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, Dispatch);

    [Fact]
    public void EveryFunctionIsDispatched() => Assert.Empty(File.Value.MissingFunctions(Dispatch));
}
