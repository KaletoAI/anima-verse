using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json.Nodes;
using AnimaNative.Embody;
using AnimaNative.Scatter;
using AnimaNative.Scene;
using static AnimaNative.Tests.EmbodyVectorAdapters;

namespace AnimaNative.Tests;

/// <summary>Task 47: enter.json shapes; existing polygon primitives stay shared with SceneView, only nearest rim is new.</summary>
internal static class EnterDispatch
{
    public static Dictionary<string, Func<JsonArray, JsonNode?>> Create()
    {
        var d = new Dictionary<string, Func<JsonArray, JsonNode?>>
        {
            ["localToWorld"] = a => Point(EnterLocation.LocalToWorld(N(a[0]), N(a[1]), N(a[2]), N(a[3]), N(a[4]))),
            ["entryOfferNear"] = a => Offer(EnterLocation.EntryOfferNear(P(a[0]), S(a[1]), ((JsonArray)a[2]!).Select(Tile), NullableN(Arg(a, 3)) ?? EnterLocation.EnterRadius)),
            ["sanitizePolygon"] = a => SceneView.SanitizePolygon(Ring(a[0])) is { } p ? RingJson(p) : null,
            ["pointInPolygon"] = a => JsonValue.Create(SceneView.PointInPolygon(N(a[0]), N(a[1]), Ring(a[2]))),
            ["polygonSignedArea"] = a => JsonValue.Create(SceneView.PolygonSignedArea(Ring(a[0]))),
            ["polygonArea"] = a => JsonValue.Create(SceneView.PolygonArea(Ring(a[0]))),
            ["polygonBounds"] = a => Bounds(a[0]),
            ["polygonDistance"] = a => JsonValue.Create(SceneView.PolygonDistance(N(a[0]), N(a[1]), Ring(a[2]))),
            ["polygonDistanceInfinite"] = a => JsonValue.Create(double.IsPositiveInfinity(SceneView.PolygonDistance(N(a[0]), N(a[1]), Ring(a[2])))),
            ["nearestRimPoint"] = a => SceneView.NearestRimPoint(N(a[0]), N(a[1]), Ring(a[2])) is { } r
                ? new JsonObject { ["x"] = r.Point.X, ["z"] = r.Point.Z, ["inward"] = Point(r.Inward), ["dist"] = r.Dist } : null,
        };
        AddProjections(d);
        return d;
    }
    private static EntryTile Tile(JsonNode? n)
    {
        var fp = n!["footprint"]!;
        return new(S(n["locId"]), new(N(fp["x"]), N(fp["z"]), N(fp["yaw"])),
            ((JsonArray)n["openings"]!).Select(o => new EntryOpening(I(o!["edge"]), Pt(o["at_world"]), Pt(o["inward"]))).ToList(),
            Ring(n["boundary"]), B(n["locked"]));
    }
    private static JsonNode? Offer(EntryOffer? o) => o is null ? null : new JsonObject
    { ["locId"] = o.LocId, ["point"] = Point(o.Point), ["edge"] = o.Edge, ["dist"] = o.Dist, ["inward"] = Point(o.Inward) };
    private static JsonNode? Bounds(JsonNode? n) => SceneView.PolygonBounds(Ring(n)) is { } b ? new JsonObject
    { ["minX"] = b.MinX, ["minZ"] = b.MinZ, ["maxX"] = b.MaxX, ["maxZ"] = b.MaxZ } : null;
}
