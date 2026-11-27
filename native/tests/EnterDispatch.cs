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
            ["atDoor"] = a => JsonValue.Create(EntryRules.AtDoor(Door(a[0]), N(a[1]), N(a[2]), Tol(a[3]))),
            ["atGate"] = a => JsonValue.Create(EntryRules.AtGate(Pt(a[0]), N(a[1]), N(a[2]), Tol(a[3]))),
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
    private static EntryDoor Door(JsonNode? n) => new(
        N(n!["x"]), N(n["z"]), N(n["out_x"]), N(n["out_z"]), N(n["width_m"]), S(n["room"]), I(n["level"]));
    private static EntryTolerance Tol(JsonNode? n) => new(
        N(n!["along_pad_m"]), N(n["across_m"]), N(n["gate_m"]));
    private static EntryTile Tile(JsonNode? n)
    {
        var gates = (Get(n, "gates") as JsonArray ?? new()).Select(g => new EntryOpening(I(g!["edge"]), Pt(g["at_world"]), Pt(g["inward"]))).ToList();
        var doors = (Get(n, "doors") as JsonArray ?? new()).Select(Door).ToList();
        return new(S(n!["locId"]), B(n["fenced"]), gates, doors, B(n["locked"]));
    }
    private static JsonNode? Offer(EntryOffer? o) => o is null ? null : new JsonObject
    { ["locId"] = o.LocId, ["point"] = Point(o.Point), ["edge"] = o.Edge, ["dist"] = o.Dist, ["inward"] = Point(o.Inward) };
    private static JsonNode? Bounds(JsonNode? n) => SceneView.PolygonBounds(Ring(n)) is { } b ? new JsonObject
    { ["minX"] = b.MinX, ["minZ"] = b.MinZ, ["maxX"] = b.MaxX, ["maxZ"] = b.MaxZ } : null;
}
