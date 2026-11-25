using System;
using System.Collections.Generic;
using System.Text.Json.Nodes;
using AnimaNative.Orders;
using AnimaNative.Tests.Vectors;
using Xunit;

namespace AnimaNative.Tests;

/// <summary>
/// shared/test-vectors/access_auto.json against <see cref="AccessAuto.Compute"/> (hand derivations: the docstring of
/// scripts/smoke_access_auto.py, which replays the same cases through room_stand.bridge_offset / bridge_scale).
/// <code>
///   accessAuto(slot {x, y, z, yaw}, travelDx, travelDz, heightCm | null, clipRefHeightM | null) → {x, y, z, yaw}
/// </code>
/// </summary>
public class AccessAutoTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("access_auto"));

    private static double N(JsonNode? n) => VectorCompare.Num(n);

    private static readonly Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch = new()
    {
        ["accessAuto"] = a =>
        {
            var s = a[0]!;
            var slot = new OrderPoint(N(s["x"]), N(s["y"]), N(s["z"]), N(s["yaw"]));
            var p = AccessAuto.Compute(slot, N(a[1]), N(a[2]), VectorCompare.NumOrNull(a[3]), VectorCompare.NumOrNull(a[4]));
            return new JsonObject { ["x"] = p.X, ["y"] = p.Y, ["z"] = p.Z, ["yaw"] = p.YawDeg };
        },
    };

    public static TheoryData<string> Cases => VectorFile.Labels("access_auto");

    [Theory, MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, Dispatch);
}
