using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using AnimaNative.Embody;
using AnimaNative.World;
using static AnimaNative.Tests.EmbodyVectorAdapters;

namespace AnimaNative.Tests;

/// <summary>Task 47: collide.json adapters; payload parser retains lintel/leaf flags, projection mirrors the TS adapter.</summary>
internal static class CollideDispatch
{
    public static Dictionary<string, Func<JsonArray, JsonNode?>> Create()
    {
        var d = new Dictionary<string, Func<JsonArray, JsonNode?>>
        {
            ["constant"] = a => Constant(S(a[0])),
            ["bodyRadius"] = a => JsonValue.Create(Collide.BodyRadius(N(a[0]))),
            ["wallSegments"] = a => Array(Collide.WallSegments(Payload(a[0]), I(a[1]), Missing(Arg(a, 2)) ? default : P(a[2])),
                s => new JsonObject { ["ax"] = s.Ax, ["az"] = s.Az, ["bx"] = s.Bx, ["bz"] = s.Bz }),
            ["clampAgainstWalls"] = a => Point(Collide.ClampAgainstWalls(P(a[0]), P(a[1]),
                ((JsonArray)a[2]!).Select(s => new WallSegment(N(s!["ax"]), N(s["az"]), N(s["bx"]), N(s["bz"]))).ToList(), N(a[3]))),
        };
        AddProjections(d);
        return d;
    }
    private static ScenePayload? Payload(JsonNode? n)
    {
        if (Missing(n)) return null;
        return ScenePayload.Parse(JsonDocument.Parse(n!.ToJsonString()).RootElement);
    }
}
