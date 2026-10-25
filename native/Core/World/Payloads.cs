using System;
using System.Collections.Generic;
using System.Globalization;
using System.Linq;
using System.Text.Json;

namespace AnimaNative.World;

/// <summary>
/// The parts of the server payloads the S1a skeleton reads, parsed out of
/// <see cref="JsonDocument"/>s. Shapes: docs/schnittstellen-3d.md § A16.5
/// (height field), § B1 (scene recipe); the TypeScript twins live in
/// packages/scene-render/src/types.ts.
/// </summary>
public static class Json
{
    public static double Num(JsonElement e, string name, double fallback = 0)
        => e.ValueKind == JsonValueKind.Object && e.TryGetProperty(name, out var v) ? Num(v, fallback) : fallback;

    public static double Num(JsonElement v, double fallback = 0)
        => v.ValueKind == JsonValueKind.Number && v.TryGetDouble(out var d) && double.IsFinite(d) ? d : fallback;

    public static double? NumOrNull(JsonElement e, string name)
        => e.TryGetProperty(name, out var v) && v.ValueKind == JsonValueKind.Number
           && v.TryGetDouble(out var d) && double.IsFinite(d) ? d : null;

    public static string Str(JsonElement e, string name, string fallback = "")
        => e.ValueKind == JsonValueKind.Object && e.TryGetProperty(name, out var v)
           && v.ValueKind == JsonValueKind.String ? v.GetString() ?? fallback : fallback;

    public static bool Bool(JsonElement e, string name)
        => e.ValueKind == JsonValueKind.Object && e.TryGetProperty(name, out var v) && v.ValueKind == JsonValueKind.True;

    public static IEnumerable<JsonElement> Arr(JsonElement e, string name)
        => e.ValueKind == JsonValueKind.Object && e.TryGetProperty(name, out var v)
           && v.ValueKind == JsonValueKind.Array ? v.EnumerateArray() : Enumerable.Empty<JsonElement>();

    public static double[] Vec(JsonElement e, string name)
        => Arr(e, name).Select(x => Num(x)).ToArray();

    public static (double X, double Z)[] Ring(JsonElement ring)
        => ring.ValueKind != JsonValueKind.Array ? Array.Empty<(double, double)>()
           : ring.EnumerateArray()
                 .Where(p => p.ValueKind == JsonValueKind.Array && p.GetArrayLength() >= 2)
                 .Select(p => (Num(p[0]), Num(p[1]))).ToArray();
}

/// <summary>
/// One regular height lattice: <c>heights[j][i]</c> at
/// <c>(origin_x + i·step, origin_z + j·step)</c>, stored row-major.
/// </summary>
public sealed class HeightGrid
{
    public double OriginX { get; }
    public double OriginZ { get; }
    public double Step { get; }
    public int Rows { get; }
    public int Cols { get; }
    public float[] Heights { get; }

    public HeightGrid(double originX, double originZ, double step, int rows, int cols, float[] heights)
    {
        OriginX = originX; OriginZ = originZ; Step = step; Rows = rows; Cols = cols; Heights = heights;
    }

    public float At(int i, int j) => Heights[j * Cols + i];

    /// <summary>
    /// Parse a grid. THE SHAPE COMES FROM THE ARRAY, like
    /// <c>sampleWorldHeight</c>: rows = number of rows, cols = length of the
    /// first row; a missing or non-finite value reads as 0.
    /// </summary>
    public static HeightGrid Parse(JsonElement e, double step)
    {
        var rowsEl = Json.Arr(e, "heights").ToArray();
        int rows = rowsEl.Length;
        int cols = rows > 0 && rowsEl[0].ValueKind == JsonValueKind.Array ? rowsEl[0].GetArrayLength() : 0;
        var h = new float[rows * cols];
        for (int j = 0; j < rows; j++)
        {
            if (rowsEl[j].ValueKind != JsonValueKind.Array) continue;
            int i = 0;
            foreach (var v in rowsEl[j].EnumerateArray())
            {
                if (i >= cols) break;
                h[j * cols + i] = (float)Json.Num(v);
                i++;
            }
        }
        return new HeightGrid(Json.Num(e, "origin_x"), Json.Num(e, "origin_z"), step, rows, cols, h);
    }

    /// <summary>
    /// Bilinear, border-clamped — line for line <c>latticeSample</c>
    /// (packages/scene-render/src/worldHeight.ts) and the server's
    /// <c>heightfield.sample_height</c> (§ A16.5). Fewer than 2×2 points = 0.
    /// </summary>
    public double Sample(double x, double z)
    {
        if (!(Cols >= 2) || !(Rows >= 2) || !(Step > 0)) return 0;
        double fx = Math.Clamp((x - OriginX) / Step, 0, Cols - 1);
        double fz = Math.Clamp((z - OriginZ) / Step, 0, Rows - 1);
        int i = Math.Min((int)Math.Floor(fx), Cols - 2);
        int j = Math.Min((int)Math.Floor(fz), Rows - 2);
        double tx = fx - i, tz = fz - j;
        double north = At(i, j) * (1 - tx) + At(i + 1, j) * tx;
        double south = At(i, j + 1) * (1 - tx) + At(i + 1, j + 1) * tx;
        return north * (1 - tz) + south * tz;
    }
}

/// <summary><c>GET /play/heightfield</c>: the overview grid plus the tile index.</summary>
public sealed class HeightfieldOverview
{
    public HeightGrid Grid { get; }
    public double TileM { get; }
    public double TileStepM { get; }
    public HashSet<(int Tx, int Tz)> TileIndex { get; }
    public string Sig { get; }

    private HeightfieldOverview(HeightGrid grid, double tileM, double tileStepM,
                                HashSet<(int, int)> index, string sig)
    {
        Grid = grid; TileM = tileM; TileStepM = tileStepM; TileIndex = index; Sig = sig;
    }

    public static HeightfieldOverview Parse(JsonElement root)
    {
        var grid = HeightGrid.Parse(root, Json.Num(root, "step_m", 4.0));
        var index = new HashSet<(int, int)>();
        foreach (var key in Json.Arr(root, "tiles"))
            if (key.ValueKind == JsonValueKind.String && TryTileKey(key.GetString(), out var k)) index.Add(k);
        return new HeightfieldOverview(grid, Json.Num(root, "tile_m", 256.0), Json.Num(root, "tile_step_m", 2.0),
                                       index, Json.Str(root, "sig"));
    }

    /// <summary>Payload spelling of a tile key: <c>"tx,tz"</c>.</summary>
    public static bool TryTileKey(string? s, out (int Tx, int Tz) key)
    {
        key = default;
        var parts = (s ?? "").Split(',');
        if (parts.Length != 2) return false;
        if (!int.TryParse(parts[0], NumberStyles.Integer, CultureInfo.InvariantCulture, out var tx)) return false;
        if (!int.TryParse(parts[1], NumberStyles.Integer, CultureInfo.InvariantCulture, out var tz)) return false;
        key = (tx, tz);
        return true;
    }
}

/// <summary>
/// A location row. From <c>GET /play/worldmap</c> it carries the placement
/// (<c>pos_x/pos_z</c> nullable, <c>yaw_deg</c>), the footprint (<c>boundary</c>, location-local
/// metres, <c>plan_width_m</c>) and <c>map3d</c>; from <c>GET /world/locations?view=3d</c> only id and
/// name (that view has no position — § A1.3: "position and derived geometry come from the world map").
/// </summary>
public sealed record LocationInfo(string Id, string Name, double? PosX, double? PosZ, double YawDeg)
{
    public bool IsPlaced => PosX is double x && double.IsFinite(x) && PosZ is double z && double.IsFinite(z);
    /// <summary><c>boundary</c> (location-local, before the yaw); null when the row has none.</summary>
    public (double X, double Z)[]? Boundary { get; init; }
    /// <summary><c>plan_width_m</c>, else 0.</summary>
    public double PlanWidthM { get; init; }
    /// <summary><c>map3d.style</c> (AV3D-1), "" when absent.</summary>
    public string Map3dStyle { get; init; } = "";
    /// <summary><c>map3d.area_model</c> truthy — <c>isAreaLocation</c> (tiles.ts).</summary>
    public bool AreaModel { get; init; }
    /// <summary>The row's <c>terrain</c> string (AV3D-7), "" when absent.</summary>
    public string Terrain { get; init; } = "";

    public static List<LocationInfo> ParseList(JsonElement root)
        => Json.Arr(root, "locations")
               .Where(l => l.ValueKind == JsonValueKind.Object)
               .Select(Parse)
               .Where(l => l.Id.Length > 0)
               .ToList();

    public static LocationInfo Parse(JsonElement l)
    {
        l.TryGetProperty("map3d", out var m3);
        var ring = l.TryGetProperty("boundary", out var b) ? Json.Ring(b) : Array.Empty<(double, double)>();
        bool area = m3.ValueKind == JsonValueKind.Object && m3.TryGetProperty("area_model", out var am)
                    && am.ValueKind is not (JsonValueKind.Null or JsonValueKind.False or JsonValueKind.Undefined)
                    && !(am.ValueKind == JsonValueKind.String && am.GetString() == "")
                    && !(am.ValueKind == JsonValueKind.Number && am.GetDouble() == 0);
        return new LocationInfo(Json.Str(l, "id"), Json.Str(l, "name"),
                                Json.NumOrNull(l, "pos_x"), Json.NumOrNull(l, "pos_z"), Json.Num(l, "yaw_deg"))
        {
            Boundary = ring.Length >= 3 ? ring : null,
            PlanWidthM = Json.Num(l, "plan_width_m"),
            Map3dStyle = Json.Str(m3, "style"),
            AreaModel = area,
            Terrain = Json.Str(l, "terrain"),
        };
    }
}

/// <summary>§ B1 <c>plates[]</c>.</summary>
public sealed record ScenePlate(int Level, (double X, double Z)[] Outline, (double X, double Z)[][] Holes,
                                double TopY, double Thickness)
{
    public string RoomId { get; init; } = "";
    public string TextureKind { get; init; } = "";
    /// <summary><c>opacity_role</c>: "upper" = the payload ghosts it (<c>style.upper_floor_opacity</c>).</summary>
    public string OpacityRole { get; init; } = "";
}

/// <summary>§ B1 <c>walls[]</c>.</summary>
public sealed record SceneWall(int Level, (double X, double Z) From, (double X, double Z) To,
                               double BaseY, double Height, double Thickness,
                               bool Glass, bool Leaf, bool DoorProp)
{
    public string RoomId { get; init; } = "";
    public string TextureKind { get; init; } = "";
    public string OpacityRole { get; init; } = "";
    /// <summary>The pane is filled by a window MODEL in <c>models[]</c> (Blender windows v16) — hidden inside like a door-prop leaf.</summary>
    public bool WindowModel { get; init; }
    /// <summary><c>outward_normal</c> (tile frame), (0, 0) when absent.</summary>
    public (double X, double Z) OutwardNormal { get; init; }
}

/// <summary>§ B1 <c>extras[]</c> — a box, centre + own size, optional XYZ Euler in degrees.</summary>
public sealed record SceneExtra(string Kind, double[] Center, double[] Size, double[]? Rotation)
{
    public int? Level { get; init; }
    public string TextureKind { get; init; } = "";
}

/// <summary>§ B1 <c>rooms[]</c>: the fields the visibility rules read.</summary>
public sealed record SceneRoom(string RoomId, int Level, bool AlwaysVisible);

/// <summary>§ B1 <c>models[]</c> — the one placement spec of § B2.</summary>
public sealed record SceneModelSpec(
    string Role, string Id, string Display, bool RoofOnly,
    Dictionary<string, string> Variants, List<Dictionary<string, string>>? ModelVariants, int Variant,
    double FixX, double FixY, double FixZ, double YawDeg, double MaxM, string Measure,
    double[]? SizeM, double AnchorX, double AnchorZ, double BottomY)
{
    private static readonly string[] Tiers = { "full", "low" };

    public string RoomId { get; init; } = "";
    public int Level { get; init; }
    public bool PlanHull { get; init; }
    /// <summary><c>placeholder_dims</c> {w, d, h} — the box a spec without a loadable mesh keeps (§ A2).</summary>
    public (double W, double D, double H)? PlaceholderDims { get; init; }
    /// <summary><c>cutouts</c>: tile-frame polygons the open interior view cuts out of an area/plan-hull model.</summary>
    public (double X, double Z)[][] Cutouts { get; init; } = Array.Empty<(double, double)[]>();

    /// <summary>
    /// <c>pickModelVariant</c> + <c>pickVariant</c> (types.ts): the model
    /// variant first (index modulo the count), then the wanted tier, else the
    /// best tier present. "" = no mesh.
    /// </summary>
    public string PickUrl(string tier = "full")
    {
        var map = Variants;
        if (ModelVariants is { Count: > 0 } list)
        {
            int n = list.Count;
            int i = ((Variant % n) + n) % n;
            map = list[i].Count > 0 ? list[i] : Variants;
        }
        foreach (var t in new[] { tier }.Concat(Tiers).Concat(map.Keys))
            if (map.TryGetValue(t, out var url) && !string.IsNullOrEmpty(url)) return url;
        return "";
    }
}

/// <summary>The scene recipe of one location, reduced to what the native client draws.</summary>
public sealed class ScenePayload
{
    public List<ScenePlate> Plates { get; } = new();
    public List<SceneWall> Walls { get; } = new();
    public List<SceneExtra> Extras { get; } = new();
    public List<SceneModelSpec> Models { get; } = new();
    public List<SceneRoom> Rooms { get; } = new();
    public HashSet<string> OutdoorRooms { get; } = new();
    public Dictionary<string, string> Style { get; } = new();
    public Dictionary<string, double> StyleNumbers { get; } = new();
    public double K { get; private set; } = 1;
    public bool AreaDetail { get; private set; }
    /// <summary><c>floor_plan</c> or <c>markers</c> non-empty — part of <c>hasInterior</c> (mountShell).</summary>
    public bool HasFloorPlanOrMarkers { get; private set; }

    public static ScenePayload Parse(JsonElement root)
    {
        var s = new ScenePayload
        {
            K = Json.Num(root, "k", 1), AreaDetail = Truthy(root, "area_detail"),
            HasFloorPlanOrMarkers = Json.Arr(root, "floor_plan").Any() || Json.Arr(root, "markers").Any(),
        };
        if (root.TryGetProperty("style", out var style) && style.ValueKind == JsonValueKind.Object)
            foreach (var p in style.EnumerateObject())
            {
                if (p.Value.ValueKind == JsonValueKind.String) s.Style[p.Name] = p.Value.GetString()!;
                else if (p.Value.ValueKind == JsonValueKind.Number) s.StyleNumbers[p.Name] = p.Value.GetDouble();
            }
        foreach (var p in Json.Arr(root, "plates"))
            s.Plates.Add(new ScenePlate((int)Json.Num(p, "level"),
                                        p.TryGetProperty("outline", out var o) ? Json.Ring(o) : Array.Empty<(double, double)>(),
                                        Json.Arr(p, "holes").Select(Json.Ring).ToArray(),
                                        Json.Num(p, "top_y"), Json.Num(p, "thickness"))
            {
                RoomId = Json.Str(p, "room_id"), TextureKind = Json.Str(p, "texture_kind"),
                OpacityRole = Json.Str(p, "opacity_role"),
            });
        foreach (var w in Json.Arr(root, "walls"))
        {
            var from = Json.Vec(w, "from");
            var to = Json.Vec(w, "to");
            if (from.Length < 2 || to.Length < 2) { s.Walls.Add(Degenerate); continue; }
            var n = Json.Vec(w, "outward_normal");
            s.Walls.Add(new SceneWall((int)Json.Num(w, "level"), (from[0], from[1]), (to[0], to[1]),
                                      Json.Num(w, "base_y"), Json.Num(w, "height"), Json.Num(w, "thickness"),
                                      Json.Bool(w, "glass"), Json.Bool(w, "leaf"), Json.Bool(w, "door_prop"))
            {
                RoomId = Json.Str(w, "room_id"), TextureKind = Json.Str(w, "texture_kind"),
                OpacityRole = Json.Str(w, "opacity_role"), WindowModel = Json.Bool(w, "window_model"),
                OutwardNormal = n.Length >= 2 ? (n[0], n[1]) : (0, 0),
            });
        }
        foreach (var e in Json.Arr(root, "extras"))
        {
            double[]? rot = e.TryGetProperty("rotation", out var r) && r.ValueKind == JsonValueKind.Array
                ? r.EnumerateArray().Select(x => Json.Num(x)).ToArray() : null;
            s.Extras.Add(new SceneExtra(Json.Str(e, "kind"), Json.Vec(e, "center"), Json.Vec(e, "size"), rot)
            {
                Level = Json.NumOrNull(e, "level") is double lv ? (int)lv : null,
                TextureKind = Json.Str(e, "texture_kind"),
            });
        }
        foreach (var r in Json.Arr(root, "rooms"))
            if (Json.Str(r, "room_id") is { Length: > 0 } id)
                s.Rooms.Add(new SceneRoom(id, (int)Json.Num(r, "level"), Json.Bool(r, "always_visible")));
        foreach (var o in Json.Arr(root, "outdoor_rooms"))
            if (o.ValueKind == JsonValueKind.String && o.GetString() is { Length: > 0 } id) s.OutdoorRooms.Add(id);
        foreach (var m in Json.Arr(root, "models"))
            s.Models.Add(ParseModel(m));
        return s;
    }

    /// <summary>JS truthiness of one field (<c>!!scene.area_detail</c>).</summary>
    private static bool Truthy(JsonElement e, string name)
        => e.TryGetProperty(name, out var v) && v.ValueKind switch
        {
            JsonValueKind.True => true,
            JsonValueKind.Number => v.GetDouble() != 0,
            JsonValueKind.String => v.GetString()!.Length > 0,
            JsonValueKind.Object or JsonValueKind.Array => true,
            _ => false,
        };

    private static readonly SceneWall Degenerate = new(0, (0, 0), (0, 0), 0, 0, 0, false, false, false);

    private static Dictionary<string, string> UrlMap(JsonElement e)
    {
        var d = new Dictionary<string, string>();
        if (e.ValueKind == JsonValueKind.Object)
            foreach (var p in e.EnumerateObject())
                if (p.Value.ValueKind == JsonValueKind.String) d[p.Name] = p.Value.GetString()!;
        return d;
    }

    /// <summary>One placement spec; shared by the recipe's <c>models[]</c> and the world props (§ A9a).</summary>
    public static SceneModelSpec ParseModel(JsonElement m)
    {
        m.TryGetProperty("fix_euler", out var fix);
        var anchor = Json.Vec(m, "anchor");
        var size = Json.Vec(m, "size_m");
        List<Dictionary<string, string>>? mv = null;
        if (m.TryGetProperty("model_variants", out var mvEl) && mvEl.ValueKind == JsonValueKind.Array)
            mv = mvEl.EnumerateArray().Select(UrlMap).ToList();
        (double, double, double)? ph = null;
        if (m.TryGetProperty("placeholder_dims", out var pd) && pd.ValueKind == JsonValueKind.Object)
            ph = (Json.Num(pd, "w"), Json.Num(pd, "d"), Json.Num(pd, "h"));
        return new SceneModelSpec(
            Json.Str(m, "role"), Json.Str(m, "id"), Json.Str(m, "display", "shell"), Json.Bool(m, "roof_only"),
            m.TryGetProperty("variants", out var v) ? UrlMap(v) : new Dictionary<string, string>(),
            mv, (int)Json.Num(m, "variant"),
            Json.Num(fix, "x"), Json.Num(fix, "y"), Json.Num(fix, "z"),
            Json.Num(m, "yaw_deg"), Json.Num(m, "max_m", 1), Json.Str(m, "measure", "xyz"),
            size.Length >= 2 ? size : null,
            anchor.Length >= 1 ? anchor[0] : 0, anchor.Length >= 2 ? anchor[1] : 0,
            Json.Num(m, "bottom_y"))
        {
            RoomId = Json.Str(m, "room_id"),
            Level = (int)Json.Num(m, "level"),
            PlanHull = Json.Bool(m, "plan_hull"),
            PlaceholderDims = ph,
            Cutouts = Json.Arr(m, "cutouts").Select(Json.Ring).Where(r => r.Length >= 3).ToArray(),
        };
    }
}

/// <summary>One fine tile of <c>/play/heightfield/tiles</c> (256 m at 2 m step, edges shared).</summary>
public sealed record HeightTile((int Tx, int Tz) Key, HeightGrid Grid)
{
    /// <summary>The tile's water field (Wasser v2 K-A, § A16.5 point 3), null on a dry tile.</summary>
    public Ground.WaterTileField? Water { get; init; }

    public static List<HeightTile> ParseBatch(JsonElement root)
    {
        double step = Json.Num(root, "step_m", 2.0);
        var list = new List<HeightTile>();
        if (!root.TryGetProperty("tiles", out var tiles) || tiles.ValueKind != JsonValueKind.Object) return list;
        foreach (var p in tiles.EnumerateObject())
            if (HeightfieldOverview.TryTileKey(p.Name, out var key))
            {
                var grid = HeightGrid.Parse(p.Value, step);
                list.Add(new HeightTile(key, grid) { Water = Ground.WaterTileField.Parse(p.Value, grid) });
            }
        return list;
    }
}
