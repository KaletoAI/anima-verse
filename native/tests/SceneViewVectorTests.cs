using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using AnimaNative.Overview;
using AnimaNative.Scatter;
using AnimaNative.Scene;
using AnimaNative.Tests.Vectors;
using AnimaNative.World;
using Xunit;
using static AnimaNative.Tests.SceneVectorAdapters;
using static AnimaNative.Tests.ScatterVectorAdapters;

namespace AnimaNative.Tests;

/// <summary>
/// shared/test-vectors/scene_view.json against <see cref="SceneView"/> (hand derivations:
/// client3d/scripts/smoke_scene_view.mjs; TS sources: client3d/src/scene/sceneView.ts, storeyDisplay.ts,
/// shellPlan.ts, client3d/src/game/streamRings.ts, polygon.ts).
///
/// <code>
///   TS fn                   C#                                shape translation
///   openable                SceneView.Openable                tile → JS truthiness of interior / flags
///   hasInterior             SceneView.HasInterior             array lengths + model roles
///   isOutdoorSpec           SceneView.IsOutdoorSpec           null room → null
///   buildingTier            SceneView.BuildingTier
///   interiorTier            SceneView.InteriorTier
///   wallVisible             SceneView.WallVisible
///   fadeStep                SceneView.FadeStep
///   fadeOpacities           SceneView.FadeOpacities           FadeLook → {roof, shell, roofVisible, …}
///   roomVisible             SceneView.RoomVisible             level null → null
///   storeyPieceOpacity      SceneView.StoreyPieceOpacity
///   farShellSource          SceneView.FarShellSource          facts object → arguments
///   farShellPiece           SceneView.FarShellPiece           piece → level, room_id, glass
///   doorMarkTransform       SceneView.DoorMarkTransform       {x, z} → P2; MarkTransform → {scale, yaw, position}
///   boundaryMarkTransform   SceneView.BoundaryMarkTransform
///   neighbourOccludes       SceneView.NeighbourOccludes
///   basementHole            SceneView.BasementHole            bounds ↔ BoundsXZ, result [minX, minZ, maxX, maxZ]
///   tileToWorld             SceneView.TileToWorld             {center:{x,y,z}, yaw} → TileFrame
///   tileDirToWorld          SceneView.TileDirToWorld
///   tileWorldBounds         SceneView.TileWorldBounds         boundary null → null
///   detectStyle             SceneView.DetectStyle             loc → map3d.style, map3d.area_model, terrain, name
///   ringFor                 SceneView.RingFor                 'near' | 'far' | 'gone' ↔ Ring
///   placeDistance           SceneView.PlaceDistance           {center, yaw, boundary, width} → Footprint
/// </code>
/// </summary>
public class SceneViewVectorTests
{
    private static readonly Lazy<VectorFile> File = new(() => VectorFile.Load("scene_view"));

    private static readonly Dictionary<string, Func<JsonArray, JsonNode?>> Dispatch = new()
    {
        ["openable"] = a =>
        {
            var t = Arity(a, 1, 1)[0];
            return SceneView.Openable(Truthy(Key(t, "interior")), Truthy(Key(t, "isBuilding")),
                                      Truthy(Key(t, "modelIsShellArea")), Truthy(Key(t, "modelIsGround")));
        },
        ["hasInterior"] = a =>
        {
            var s = Arity(a, 1, 1)[0];
            int Len(string k) => ((JsonArray)Key(s, k)!).Count;
            return SceneView.HasInterior(Len("plates"), Len("floor_plan"), Len("walls"), Len("extras"), Len("markers"),
                ((JsonArray)Key(s, "models")!).Select(m => StrOrNull(Key(m, "role"))));
        },
        ["isOutdoorSpec"] = a => SceneView.IsOutdoorSpec(StrOrNull(Arity(a, 3, 3)[0]), Strings(a[1]), Strings(a[2])),
        ["buildingTier"] = a => SceneView.BuildingTier(Num(Arity(a, 2, 2)[0]), Str(a[1])),
        ["interiorTier"] = a => SceneView.InteriorTier(Bool(Arity(a, 2, 2)[0]), Bool(a[1])),
        ["wallVisible"] = a =>
        {
            var n = Arity(a, 8, 8).Select(Num).ToArray();
            return SceneView.WallVisible(n[0], n[1], n[2], n[3], n[4], n[5], n[6], n[7]);
        },
        ["fadeStep"] = a => SceneView.FadeStep(Num(Arity(a, 3, 3)[0]), Num(a[1]), Num(a[2])),
        ["fadeOpacities"] = a =>
        {
            var f = SceneView.FadeOpacities(Num(Arity(a, 1, 1)[0]));
            return new JsonObject
            {
                ["roof"] = f.Roof, ["shell"] = f.Shell, ["roofVisible"] = f.RoofVisible, ["shellShadow"] = f.ShellShadow,
                ["interiorVisible"] = f.InteriorVisible, ["labelsVisible"] = f.LabelsVisible,
            };
        },
        ["roomVisible"] = a => SceneView.RoomVisible(Bool(Arity(a, 3, 3)[0]), VectorCompare.NumOrNull(a[1]), Num(a[2])),
        ["storeyPieceOpacity"] = a => SceneView.StoreyPieceOpacity(Num(Arity(a, 3, 3)[0]), Num(a[1]), Num(a[2])),
        ["farShellSource"] = a =>
        {
            var f = Arity(a, 1, 1)[0];
            return SceneView.FarShellSource(Bool(Key(f, "isBuilding")), Bool(Key(f, "natureSite")), Bool(Key(f, "areaDetail")),
                                            Bool(Key(f, "hasBuildingModel")), Num(Key(f, "plates")), Num(Key(f, "walls")));
        },
        ["farShellPiece"] = a =>
        {
            var p = Arity(a, 2, 2)[1];
            return SceneView.FarShellPiece(Str(a[0]), Num(Key(p, "level")), StrOrNull(Key(p, "room_id")), Truthy(Key(p, "glass")));
        },
        ["doorMarkTransform"] = a => Mark(SceneView.DoorMarkTransform(Num(Arity(a, 5, 5)[0]), Num(a[1]), XZ(a[2]), XZ(a[3]), Num(a[4]))),
        ["boundaryMarkTransform"] = a => Mark(SceneView.BoundaryMarkTransform(Num(Arity(a, 5, 5)[0]), XZ(a[1]), Num(a[2]), Num(a[3]), Num(a[4]))),
        ["neighbourOccludes"] = a =>
        {
            Arity(a, 3, 4);
            var n = a[2];
            return SceneView.NeighbourOccludes(XZ(a[0]), XZ(a[1]),
                new Neighbour(Num(Key(n, "x")), Num(Key(n, "z")), Num(Key(n, "width")), Num(Key(n, "height"))),
                Arg(a, 3) is { } s && Bool(s));
        },
        ["basementHole"] = a =>
        {
            Arity(a, 4, 4);
            var b = a[0];
            var r = SceneView.BasementHole(new BoundsXZ(Num(Key(b, "minX")), Num(Key(b, "maxX")), Num(Key(b, "minZ")), Num(Key(b, "maxZ"))),
                                           XZ(a[1]), XZ(a[2]), Num(a[3]));
            return Nums(r);
        },
        ["tileToWorld"] = a =>
        {
            Arity(a, 3, 4);
            return Obj(SceneView.TileToWorld(Frame(a[0]), Num(a[1]), Num(a[2]), Arg(a, 3) is { } y ? Num(y) : 0));
        },
        ["tileDirToWorld"] = a =>
        {
            var d = SceneView.TileDirToWorld(Num(Key(Arity(a, 3, 3)[0], "yaw")), Num(a[1]), Num(a[2]));
            return new JsonObject { ["x"] = d.X, ["z"] = d.Z };
        },
        ["tileWorldBounds"] = a =>
        {
            var t = Arity(a, 1, 1)[0];
            var b = SceneView.TileWorldBounds(Frame(t), Key(t, "boundary") is { } r ? Ring(r) : null);
            return b is { } v ? new JsonObject { ["minX"] = v.MinX, ["minZ"] = v.MinZ, ["maxX"] = v.MaxX, ["maxZ"] = v.MaxZ } : null;
        },
        ["detectStyle"] = a =>
        {
            var l = Arity(a, 1, 1)[0];
            var m3 = Key(l, "map3d");
            return SceneView.DetectStyle(StrOrNull(Key(m3, "style")), Truthy(Key(m3, "area_model")),
                                         StrOrNull(Key(l, "terrain")), StrOrNull(Key(l, "name")));
        },
        ["ringFor"] = a => RingName(SceneView.RingFor(Num(Arity(a, 4, 4)[0]), RingOf(Str(a[1])), Bool(a[2]), Num(a[3]))),
        ["placeDistance"] = a =>
        {
            var p = Arity(a, 2, 2)[0];
            var fp = new Footprint(XZ(Key(p, "center")), Num(Key(p, "yaw")),
                                   Key(p, "boundary") is { } r ? Ring(r).ToArray() : null, Num(Key(p, "width")));
            return SceneView.PlaceDistance(fp, ((JsonArray)a[1]!).Select(XZ));
        },
    };

    /// <summary>JS truthiness of a JSON value (absent = undefined = false).</summary>
    private static bool Truthy(JsonNode? n)
    {
        if (n is null) return false;
        if (n is JsonArray or JsonObject) return true;
        var el = Element(n);
        return el.ValueKind switch
        {
            JsonValueKind.True => true,
            JsonValueKind.Number => el.GetDouble() != 0,
            JsonValueKind.String => el.GetString()!.Length > 0,
            _ => false,
        };
    }

    private static List<string> Strings(JsonNode? n) => ((JsonArray)n!).Select(Str).ToList();

    private static TileFrame Frame(JsonNode? t) => new(XYZ(Key(t, "center")), Num(Key(t, "yaw")));

    private static JsonObject Mark(MarkTransform m) => new()
    {
        ["scale"] = Arr(m.Scale), ["yaw"] = m.Yaw, ["position"] = Arr(m.Position),
    };

    private static AnimaNative.World.Ring RingOf(string s) => s switch
    {
        "near" => AnimaNative.World.Ring.Near, "far" => AnimaNative.World.Ring.Far, "gone" => AnimaNative.World.Ring.Gone,
        _ => throw new ArgumentException($"unknown ring {s}"),
    };

    private static string RingName(AnimaNative.World.Ring r) => r.ToString().ToLowerInvariant();

    public static TheoryData<string> Cases => VectorFile.Labels("scene_view");

    [Theory]
    [MemberData(nameof(Cases))]
    public void Case(string label) => File.Value.AssertCase(label, Dispatch);

    [Fact]
    public void EveryFunctionIsDispatched() => Assert.Empty(File.Value.MissingFunctions(Dispatch));
}
