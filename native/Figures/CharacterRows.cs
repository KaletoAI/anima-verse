using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using AnimaNative.World;

namespace AnimaNative.Figures;

/// <summary>
/// One character row of <c>GET /play/worldmap</c> (§ A1.4), reduced to what
/// the spike draws: where it stands, how tall it is, which mesh it wears.
/// </summary>
public sealed record CharacterRow(
    string Name, string LocationId, double? PosX, double? PosZ, double? HeightCm, string? ModelSig,
    TravelInfo? Travel)
{
    public bool HasPos => PosX.HasValue && PosZ.HasValue;

    public static List<CharacterRow> ParseList(JsonElement root)
        => Json.Arr(root, "characters")
               .Where(c => c.ValueKind == JsonValueKind.Object)
               .Select(Parse)
               .Where(c => c.Name.Length > 0)
               .ToList();

    private static CharacterRow Parse(JsonElement c)
    {
        double? px = null, pz = null;
        if (c.TryGetProperty("pos", out var pos) && pos.ValueKind == JsonValueKind.Object)
        {
            px = Json.NumOrNull(pos, "x");
            pz = Json.NumOrNull(pos, "z");
        }
        TravelInfo? travel = null;
        if (c.TryGetProperty("travel", out var tr) && tr.ValueKind == JsonValueKind.Object)
        {
            List<(double X, double Z)>? wp = null;
            if (tr.TryGetProperty("waypoints", out var w) && w.ValueKind == JsonValueKind.Array)
                wp = Json.Ring(w).ToList();
            travel = new TravelInfo(wp, Json.NumOrNull(tr, "progress_m"));
        }
        string? sig = c.TryGetProperty("model_sig", out var s) && s.ValueKind == JsonValueKind.String ? s.GetString() : null;
        return new CharacterRow(Json.Str(c, "name"), Json.Str(c, "location_id"), px, pz,
                                Json.NumOrNull(c, "height_cm"), sig, travel);
    }
}

/// <summary>§ A11 <c>travel</c>: the metre polyline and the distance already walked (both null under fog).</summary>
public sealed record TravelInfo(List<(double X, double Z)>? Waypoints, double? ProgressM);

/// <summary>
/// The parts of a world-map LOCATION row the far-view huddle needs (the browser's
/// <c>buildPlace</c>): pin, yaw, footprint width (bounding box of
/// <c>boundary</c>, else <c>plan_width_m</c>, <c>footprintWidth</c>) and whether
/// it is a building (<c>!map3d.area_model</c>, <c>isAreaLocation</c>).
/// </summary>
public sealed record MapPlace(string Id, double X, double Z, double YawDeg, double Width, bool IsBuilding)
{
    /// <summary>Placed rows only — the browser builds a tile only for those (<c>footprintCentre</c>).</summary>
    public static Dictionary<string, MapPlace> ParsePlaced(JsonElement root)
    {
        var map = new Dictionary<string, MapPlace>();
        foreach (var l in Json.Arr(root, "locations"))
        {
            if (l.ValueKind != JsonValueKind.Object) continue;
            var id = Json.Str(l, "id");
            var x = Json.NumOrNull(l, "pos_x");
            var z = Json.NumOrNull(l, "pos_z");
            if (id.Length == 0 || x is null || z is null) continue;
            l.TryGetProperty("map3d", out var m3);
            var ring = l.TryGetProperty("boundary", out var b) && b.ValueKind == JsonValueKind.Array ? Json.Ring(b)
                     : m3.ValueKind == JsonValueKind.Object && m3.TryGetProperty("boundary", out var mb) ? Json.Ring(mb)
                     : Array.Empty<(double X, double Z)>();
            double width = 0;
            if (ring.Length > 0)
                width = Math.Max(ring.Max(p => p.X) - ring.Min(p => p.X), ring.Max(p => p.Z) - ring.Min(p => p.Z));
            else
            {
                var w = Json.NumOrNull(l, "plan_width_m")
                        ?? (m3.ValueKind == JsonValueKind.Object ? Json.NumOrNull(m3, "plan_width_m") : null);
                width = w is > 0 ? w.Value : 0;
            }
            bool area = m3.ValueKind == JsonValueKind.Object && m3.TryGetProperty("area_model", out var am)
                        && am.ValueKind is not (JsonValueKind.Null or JsonValueKind.False or JsonValueKind.Undefined)
                        && !(am.ValueKind == JsonValueKind.String && am.GetString() == "");
            map[id] = new MapPlace(id, x.Value, z.Value, Json.Num(l, "yaw_deg"), width, !area);
        }
        return map;
    }
}

/// <summary>Where a character is drawn on the open map, and which rule said so.</summary>
public readonly record struct FigureSpot(double X, double Z, string Rule);

/// <summary>
/// WHICH characters stand on the map and WHERE — the browser's far view
/// (client3d/src/main.ts <c>computeNpcPlacements</c> with every detail view
/// closed, which is the only view the spike has: it draws no interiors).
/// Pure, so <c>--check</c> derives every case by hand.
///
///   1. <b>journey</b> (<c>travellerState</c>): <c>travel</c> with ≥ 2
///      <c>waypoints</c> AND a <c>progress_m</c> → the point
///      <c>progress_m</c> metres along the polyline (§ A11, the ONE formula;
///      progress clamped to [0, total]). A journey whose route is withheld
///      (fog) or degenerate falls back to <c>pos</c> when there is one.
///   2. <b>tile</b> (<c>placementOf</c> → tile): the character's
///      <c>location_id</c> names a PLACED location → the far-view huddle
///      (<c>slotOffset</c>): characters of that location sorted by name, index
///      i of n; a building lines them up in front of its south side at
///      x = (i − (n−1)/2)·2.3, z = width·0.36, an area location stands them on
///      a 2.6 m ring at angle 2π·i/n; tile-local → world with the pin and
///      +yaw (<c>tileToWorld</c>). Room and seat placement only exist while an
///      interior is revealed — never in this client.
///   3. <b>free</b>: no placed location but a <c>pos</c> → that point
///      (wilderness, § A1.4).
///   4. otherwise <b>offmap</b> (not drawn).
///
/// Height is the caller's: the world ground at (x, z) (<see cref="WorldHeight.GroundAt"/>).
/// The avatar is treated like every other character (the browser's embodied
/// avatar has its own driver; the spike has no avatar control).
/// </summary>
public static class FigurePlacement
{
    public static Dictionary<string, FigureSpot> Resolve(IReadOnlyList<CharacterRow> rows,
                                                         IReadOnlyDictionary<string, MapPlace> placed)
    {
        var spots = new Dictionary<string, FigureSpot>();
        var byLoc = new Dictionary<string, List<CharacterRow>>();
        foreach (var c in rows)
        {
            if (c.Travel is { } tr)
            {
                if (tr.Waypoints is { Count: >= 2 } wp && tr.ProgressM is { } prog)
                {
                    var (x, z) = PointAtDistance(wp, Math.Clamp(prog, 0, PolylineLength(wp)));
                    spots[c.Name] = new FigureSpot(x, z, "journey");
                    continue;
                }
                if (c.HasPos)
                {
                    spots[c.Name] = new FigureSpot(c.PosX!.Value, c.PosZ!.Value, "journey-pos");
                    continue;
                }
            }
            if (c.LocationId.Length > 0 && placed.ContainsKey(c.LocationId))
            {
                if (!byLoc.TryGetValue(c.LocationId, out var list)) byLoc[c.LocationId] = list = new List<CharacterRow>();
                list.Add(c);
                continue;
            }
            if (c.HasPos) spots[c.Name] = new FigureSpot(c.PosX!.Value, c.PosZ!.Value, "free");
        }
        foreach (var (locId, chars) in byLoc)
        {
            var place = placed[locId];
            chars.Sort((a, b) => string.Compare(a.Name, b.Name, StringComparison.InvariantCulture));
            for (int i = 0; i < chars.Count; i++)
            {
                var (lx, lz) = SlotOffset(place, i, chars.Count);
                var (x, z) = TileToWorld(place, lx, lz);
                spots[chars[i].Name] = new FigureSpot(x, z, "tile");
            }
        }
        return spots;
    }

    /// <summary><c>slotOffset</c> (main.ts): the row in front of a building, the ring on an open place.</summary>
    public static (double X, double Z) SlotOffset(MapPlace place, int index, int count)
    {
        if (place.IsBuilding) return ((index - (count - 1) / 2.0) * 2.3, place.Width * 0.36);
        double angle = index / (double)Math.Max(count, 1) * Math.PI * 2;
        return (Math.Cos(angle) * 2.6, Math.Sin(angle) * 2.6);
    }

    /// <summary><c>tileToWorld</c> (tiles.ts): turn by +yaw, then add the pin (§ A1.1).</summary>
    public static (double X, double Z) TileToWorld(MapPlace place, double lx, double lz)
    {
        double yaw = place.YawDeg * Math.PI / 180.0, c = Math.Cos(yaw), s = Math.Sin(yaw);
        return (place.X + lx * c + lz * s, place.Z - lx * s + lz * c);
    }

    public static double PolylineLength(IReadOnlyList<(double X, double Z)> wp)
    {
        double total = 0;
        for (int i = 0; i + 1 < wp.Count; i++) total += Dist(wp[i], wp[i + 1]);
        return total;
    }

    /// <summary>§ A11: walk <paramref name="d"/> metres down the polyline; past the end = the last point.</summary>
    public static (double X, double Z) PointAtDistance(IReadOnlyList<(double X, double Z)> wp, double d)
    {
        for (int i = 0; i + 1 < wp.Count; i++)
        {
            double len = Dist(wp[i], wp[i + 1]);
            if (d <= len)
            {
                double t = len > 0 ? d / len : 0;
                return (wp[i].X + (wp[i + 1].X - wp[i].X) * t, wp[i].Z + (wp[i + 1].Z - wp[i].Z) * t);
            }
            d -= len;
        }
        return wp[^1];
    }

    private static double Dist((double X, double Z) a, (double X, double Z) b)
        => Math.Sqrt((b.X - a.X) * (b.X - a.X) + (b.Z - a.Z) * (b.Z - a.Z));
}
