using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using AnimaNative.Overview;
using AnimaNative.Scatter;
using AnimaNative.Scene;

namespace AnimaNative.World;

// The rest of the § B1 scene payload (packages/scene-render/src/types.ts, server app/core/scene_recipe.py):
// every block the native client parses even where a later task is the first to use it (storeys, places,
// stairs, door props, slots, lights, water). Shapes follow the TS interfaces field for field; absent
// optional numbers are null, absent optional strings "", absent lists empty.

/// <summary>§ B1 <c>levels[]</c>: one declared storey and its floor height.</summary>
public sealed record SceneLevel(int Level, double FloorY);

/// <summary>§ B1 <c>stairs[]</c> (addendum "Treppen v2"): one flight as data, scene frame.</summary>
public sealed record SceneStairs(
    int Id, int FromLevel, int ToLevel, P2 At, double DirDeg, double RunM, double RiseM, int Steps,
    double TreadM, double WidthM, Vec3 Foot, Vec3 Head, P2[] Footprint);

/// <summary>§ B1 <c>floor_plan[]</c>: one storey-0 room hull (E5a), no heights.</summary>
public sealed record SceneFloor(string RoomId, P2[] PolygonWorld, string FloorKind, bool Closed)
{
    /// <summary><c>map_water</c>: the painted water area this room lies in (area id, kind), null when absent.</summary>
    public (string AreaId, string Kind)? MapWater { get; init; }
}

/// <summary>§ B1 <c>markers[]</c>: a place (seat, bed, stand …) with its slots, world metres of the scene frame.</summary>
public sealed record SceneMarker(
    string RoomId, string Id, string Group, string Label, int Capacity, P2 AtWorld, P2[] Slots, double YWorld,
    string Source)
{
    public double? RootOffset { get; init; }
    public double? Facing { get; init; }
    public double? Tilt { get; init; }
    public double? Roll { get; init; }
    /// <summary>The prop anchor a prop marker lifts with (<c>markerLiftPoint</c>); null for a room marker.</summary>
    public P2? Anchor { get; init; }
    public bool Diorama { get; init; }
}

/// <summary>§ B1 <c>doorways[]</c>: one threshold (door or passage) between rooms or to the outside.</summary>
public sealed record SceneDoorway(
    int Level, P2 AtWorld, P2 Along, string Type, double WidthM, double HeightM, double BaseY, string[] Rooms,
    bool Outside)
{
    public bool Hull { get; init; }
    public P2? OutwardNormal { get; init; }
}

/// <summary>§ B1 <c>corridors[]</c>: the per-storey corridor room (§ A13b/c).</summary>
public sealed record SceneCorridor(string RoomId, int Level, P2 Anchor, P2[] Outline);

/// <summary>§ B1 <c>problems[]</c>: a composer finding the client may toast (not <c>scope: "editor"</c>).</summary>
public sealed record SceneProblem(string Kind, string Message)
{
    public string LocationId { get; init; } = "";
    public string RoomId { get; init; } = "";
    public string Scope { get; init; } = "";
    public int? Level { get; init; }
    public int? Edge { get; init; }
    public int? RoomCount { get; init; }
    public string[] RoomIds { get; init; } = Array.Empty<string>();
    public int[] Levels { get; init; } = Array.Empty<int>();
    public string[] PropIds { get; init; } = Array.Empty<string>();
    public string[] PropNames { get; init; } = Array.Empty<string>();
}

/// <summary>§ B1 <c>boundary_openings[]</c>: an entrance on the footprint edge.</summary>
public sealed record SceneBoundaryOpening(int Edge, P2 AtWorld, double WidthM, string Type, P2 Inward)
{
    public string RoomId { get; init; } = "";
}

/// <summary>§ B1 <c>rooms[].openings[]</c>: an opening on one outline edge (plan fractions).</summary>
public sealed record SceneOpening(int Edge, double At, double WidthM, double HeightM, double SillM, string Type)
{
    public string To { get; init; } = "";
    public string PropId { get; init; } = "";
    public bool Mirrored { get; init; }
}

/// <summary>§ B1 <c>rooms[].overlay</c>: a zone lying on an area model's surface.</summary>
public sealed record SceneRoomOverlay(P2 Centre, double RectX, double RectZ, double RectW, double RectD, double Y);

/// <summary>§ B1 <c>rooms[].ambience</c> (v17): daylight factor and an optional sRGB tint ("" = none).</summary>
public sealed record SceneAmbience(double Daylight, string Tint);

/// <summary>§ B2 <c>door</c>: a door prop's opening index, hinge side, swing sign and leaf box.</summary>
public sealed record SceneDoor(int Opening, string Hinge, int Swing)
{
    public (Vec3 Min, Vec3 Max)? LeafBox { get; init; }
}

/// <summary>§ B2 <c>light</c> (v17): a prop's point light.</summary>
public sealed record ScenePropLight(
    string Color, double Intensity, double RangeM, string Flicker, string When, double GlowM, P2 Offset, double HeightM);

/// <summary>One region of § B2 <c>water</c> (scene v18): a still water surface inside a prop/diorama.</summary>
public sealed record SceneWaterRegion(P2[] Outline, P2[][] Holes, double Y, double BedY, string Tint, double Opacity,
                                      double SwimFromM);

/// <summary>§ B2 <c>cut_plane</c>: the kept half-space n·p + c ≥ 0 in the location frame.</summary>
public sealed record SceneCutPlane(Vec3 Normal, double Constant);

/// <summary>§ B2 <c>slots</c>: one material slot's value (picture URL and/or preset name).</summary>
public sealed record SceneSlotValue(string Image, string Preset);

/// <summary>§ B1 <c>figures</c> (ignored by the browser: 1.70 m is a client constant) — parsed for completeness.</summary>
public sealed record SceneFigures(double BaseHeightMWorld, double StandClearance);

/// <summary>The readers of the parts above (shared by <see cref="ScenePayload.Parse"/> and <see cref="ScenePayload.ParseModel"/>).</summary>
public static class SceneJson
{
    public static P2 Pt(JsonElement e, string name)
    {
        var v = Json.Vec(e, name);
        return new P2(v.Length > 0 ? v[0] : 0, v.Length > 1 ? v[1] : 0);
    }

    public static P2? PtOrNull(JsonElement e, string name)
    {
        if (!e.TryGetProperty(name, out var a) || a.ValueKind != JsonValueKind.Array || a.GetArrayLength() < 2) return null;
        return new P2(Json.Num(a[0]), Json.Num(a[1]));
    }

    public static Vec3 V3(JsonElement e, string name)
    {
        var v = Json.Vec(e, name);
        return new Vec3(v.Length > 0 ? v[0] : 0, v.Length > 1 ? v[1] : 0, v.Length > 2 ? v[2] : 0);
    }

    public static P2[] Ring(JsonElement e, string name)
        => e.TryGetProperty(name, out var r) ? Json.Ring(r).Select(p => new P2(p.X, p.Z)).ToArray() : Array.Empty<P2>();

    public static int? IntOrNull(JsonElement e, string name) => Json.NumOrNull(e, name) is double d ? (int)d : null;

    public static string[] Strings(JsonElement e, string name)
        => Json.Arr(e, name).Where(x => x.ValueKind == JsonValueKind.String).Select(x => x.GetString()!).ToArray();

    public static SceneLevel Level(JsonElement l) => new((int)Json.Num(l, "level"), Json.Num(l, "floor_y"));

    public static SceneStairs Stairs(JsonElement s) => new(
        (int)Json.Num(s, "id"), (int)Json.Num(s, "from_level"), (int)Json.Num(s, "to_level"), Pt(s, "at"),
        Json.Num(s, "dir_deg"), Json.Num(s, "run_m"), Json.Num(s, "rise_m"), (int)Json.Num(s, "steps"),
        Json.Num(s, "tread_m"), Json.Num(s, "width_m"), V3(s, "foot"), V3(s, "head"), Ring(s, "footprint"));

    public static SceneFloor Floor(JsonElement f)
    {
        (string, string)? water = null;
        if (f.TryGetProperty("map_water", out var w) && w.ValueKind == JsonValueKind.Object)
            water = (Json.Str(w, "area_id"), Json.Str(w, "kind"));
        return new SceneFloor(Json.Str(f, "room_id"), Ring(f, "polygon_world"), Json.Str(f, "floor_kind"),
                              Json.Bool(f, "closed")) { MapWater = water };
    }

    public static SceneMarker Marker(JsonElement m) => new(
        Json.Str(m, "room_id"), Json.Str(m, "id"), Json.Str(m, "group"), Json.Str(m, "label"),
        (int)Json.Num(m, "capacity"), Pt(m, "at_world"), Ring(m, "slots"), Json.Num(m, "y_world"), Json.Str(m, "source"))
    {
        RootOffset = Json.NumOrNull(m, "root_offset"), Facing = Json.NumOrNull(m, "facing"),
        Tilt = Json.NumOrNull(m, "tilt"), Roll = Json.NumOrNull(m, "roll"),
        Anchor = PtOrNull(m, "anchor"), Diorama = Json.Bool(m, "diorama"),
    };

    public static SceneDoorway Doorway(JsonElement d) => new(
        (int)Json.Num(d, "level"), Pt(d, "at_world"), Pt(d, "along"), Json.Str(d, "type", "door"),
        Json.Num(d, "width_m"), Json.Num(d, "height_m"), Json.Num(d, "base_y"), Strings(d, "rooms"), Json.Bool(d, "outside"))
    {
        Hull = Json.Bool(d, "hull"), OutwardNormal = PtOrNull(d, "outward_normal"),
    };

    public static SceneCorridor Corridor(JsonElement c)
        => new(Json.Str(c, "room_id"), (int)Json.Num(c, "level"), Pt(c, "anchor"), Ring(c, "outline"));

    public static SceneProblem Problem(JsonElement p) => new(Json.Str(p, "kind"), Json.Str(p, "message"))
    {
        LocationId = Json.Str(p, "location_id"), RoomId = Json.Str(p, "room_id"), Scope = Json.Str(p, "scope"),
        Level = IntOrNull(p, "level"), Edge = IntOrNull(p, "edge"), RoomCount = IntOrNull(p, "room_count"),
        RoomIds = Strings(p, "room_ids"),
        Levels = Json.Arr(p, "levels").Where(x => x.ValueKind == JsonValueKind.Number).Select(x => (int)Json.Num(x)).ToArray(),
        PropIds = Strings(p, "prop_ids"), PropNames = Strings(p, "prop_names"),
    };

    public static SceneBoundaryOpening BoundaryOpening(JsonElement b) => new(
        (int)Json.Num(b, "edge"), Pt(b, "at_world"), Json.Num(b, "width_m"), Json.Str(b, "type"), Pt(b, "inward"))
    {
        RoomId = Json.Str(b, "room_id"),
    };

    public static SceneOpening Opening(JsonElement o) => new(
        (int)Json.Num(o, "edge"), Json.Num(o, "at"), Json.Num(o, "width_m"), Json.Num(o, "height_m"),
        Json.Num(o, "sill_m"), Json.Str(o, "type"))
    {
        To = Json.Str(o, "to"), PropId = Json.Str(o, "prop_id"), Mirrored = Json.Bool(o, "mirrored"),
    };

    public static SceneRoomOverlay? Overlay(JsonElement r)
    {
        if (!r.TryGetProperty("overlay", out var o) || o.ValueKind != JsonValueKind.Object) return null;
        o.TryGetProperty("rect", out var rect);
        return new SceneRoomOverlay(Pt(o, "centre"), Json.Num(rect, "x"), Json.Num(rect, "z"), Json.Num(rect, "w"),
                                    Json.Num(rect, "d"), Json.Num(o, "y"));
    }

    public static SceneAmbience? Ambience(JsonElement r)
    {
        if (!r.TryGetProperty("ambience", out var a) || a.ValueKind != JsonValueKind.Object) return null;
        return new SceneAmbience(Json.Num(a, "daylight", 1), Json.Str(a, "tint"));
    }

    public static SceneSurface? Surface(JsonElement m)
    {
        if (!m.TryGetProperty("surface", out var s) || s.ValueKind != JsonValueKind.Object) return null;
        var values = Json.Arr(s, "values").Select(v => v.ValueKind == JsonValueKind.Number ? Json.Num(v) : (double?)null).ToArray();
        return new SceneSurface(Json.Num(s, "step"), Pt(s, "origin"), (int)Json.Num(s, "cols"), (int)Json.Num(s, "rows"),
                                values, V3(s, "box_min"), V3(s, "box_max"), V3(s, "extent_snapped"));
    }

    private static (Vec3, Vec3)? LeafBox(JsonElement e, string name)
        => e.TryGetProperty(name, out var b) && b.ValueKind == JsonValueKind.Object ? (V3(b, "min"), V3(b, "max")) : null;

    public static (Vec3 Min, Vec3 Max)? TopLeafBox(JsonElement m) => LeafBox(m, "leaf_bbox");

    public static SceneDoor? Door(JsonElement m)
    {
        if (!m.TryGetProperty("door", out var d) || d.ValueKind != JsonValueKind.Object) return null;
        return new SceneDoor((int)Json.Num(d, "opening"), Json.Str(d, "hinge"), (int)Json.Num(d, "swing", 1))
        {
            LeafBox = LeafBox(d, "leaf_bbox"),
        };
    }

    public static ScenePropLight? Light(JsonElement m)
    {
        if (!m.TryGetProperty("light", out var l) || l.ValueKind != JsonValueKind.Object) return null;
        return new ScenePropLight(Json.Str(l, "color"), Json.Num(l, "intensity"), Json.Num(l, "range_m"),
                                  Json.Str(l, "flicker", "none"), Json.Str(l, "when", "always"), Json.Num(l, "glow_m"),
                                  Pt(l, "offset_m"), Json.Num(l, "height_m"));
    }

    public static SceneWaterRegion[] Water(JsonElement m)
    {
        if (!m.TryGetProperty("water", out var w) || w.ValueKind != JsonValueKind.Object) return Array.Empty<SceneWaterRegion>();
        return Json.Arr(w, "regions").Select(r => new SceneWaterRegion(
            Ring(r, "outline"), Json.Arr(r, "holes").Select(h => Json.Ring(h).Select(p => new P2(p.X, p.Z)).ToArray()).ToArray(),
            Json.Num(r, "y"), Json.Num(r, "bed_y"), Json.Str(r, "tint"), Json.Num(r, "opacity"), Json.Num(r, "swim_from_m")))
            .ToArray();
    }

    public static SceneCutPlane? CutPlane(JsonElement m)
    {
        if (!m.TryGetProperty("cut_plane", out var c) || c.ValueKind != JsonValueKind.Object) return null;
        return new SceneCutPlane(V3(c, "normal"), Json.Num(c, "constant"));
    }

    public static Dictionary<string, SceneSlotValue> Slots(JsonElement m)
    {
        var d = new Dictionary<string, SceneSlotValue>();
        if (m.TryGetProperty("slots", out var s) && s.ValueKind == JsonValueKind.Object)
            foreach (var p in s.EnumerateObject())
                if (p.Value.ValueKind == JsonValueKind.Object)
                    d[p.Name] = new SceneSlotValue(Json.Str(p.Value, "image"), Json.Str(p.Value, "preset"));
        return d;
    }
}
