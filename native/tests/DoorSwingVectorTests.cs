using System;
using System.Collections.Generic;
using System.Text.Json.Nodes;
using AnimaNative.Scene;
using AnimaNative.Tests.Vectors;
using Xunit;
using static AnimaNative.Tests.SceneVectorAdapters;
using static AnimaNative.Tests.ScatterVectorAdapters;

namespace AnimaNative.Tests;

/// <summary>
/// shared/test-vectors/door_swing.json against <see cref="DoorSwing"/> (hand derivations and wrappers:
/// client3d/scripts/smoke_door_swing.mjs; TS source client3d/src/game/doorSwing.ts). A null distance is +∞ both ways.
/// </summary>
public class DoorSwingVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("door_swing"));

    private static double Inf(JsonNode? n) => n is null ? double.PositiveInfinity : Num(n);

    private static readonly Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch = new()
    {
        ["doorConstants"] = a =>
        {
            Arity(a, 0, 0);
            return new JsonObject { ["range"] = DoorSwing.OpenRange, ["openDeg"] = DoorSwing.OpenDeg, ["rate"] = DoorSwing.SwingRate };
        },
        ["doorTargetAngle"] = a => DoorSwing.DoorTargetAngle(Inf(Arity(a, 3, 3)[0]), Bool(a[1]), Int(a[2])),
        ["doorDistance"] = a =>
        {
            double d = DoorSwing.DoorDistance(Int(Arity(a, 3, 3)[0]), Int(a[1]), Inf(a[2]));
            return double.IsPositiveInfinity(d) ? null : d;
        },
        ["easeAngle"] = a => Arity(a, 3, 4).Count == 4
            ? DoorSwing.EaseAngle(Num(a[0]), Num(a[1]), Num(a[2]), Num(a[3]))
            : DoorSwing.EaseAngle(Num(a[0]), Num(a[1]), Num(a[2])),
        ["doorSwingFrames"] = a =>
        {
            double target = DoorSwing.DoorTargetAngle(Num(Arity(a, 2, 2)[1]), true, 1);
            double angle = Num(a[0]);
            int frames = 0;
            while (angle != target && frames < 100)
            {
                angle = DoorSwing.EaseAngle(angle, target, 1.0 / 60, DoorSwing.SwingRate);
                frames++;
            }
            return frames;
        },
    };

    public static TheoryData<string> Cases => VectorFile.Labels("door_swing");

    [Theory]
    [MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, Dispatch);

    [Fact]
    public void EveryFunctionIsDispatched() => Assert.Empty(File.Value.MissingFunctions(Dispatch));
}
