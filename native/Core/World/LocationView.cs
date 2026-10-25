using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;

namespace AnimaNative.World;

/// <summary>The streaming ring of a location (client3d/src/game/streamRings.ts).</summary>
public enum Ring { Near, Far, Gone }

/// <summary>
/// WHAT THE BROWSER'S OVERVIEW SHOWS OF ONE LOCATION — the decisions alone, without a mesh, ported from
/// client3d so the native client draws the same parts of every scene recipe (Task S3c):
///
///   • the streaming ring (<c>streamRings.ringFor</c> over <c>placeDistance</c> to the stream points — the
///     avatar's position and the camera focus; the avatar's location and the open one are pinned near). A
///     <c>gone</c> location is not mounted in the browser at all;
///   • the OPEN location (main.ts <c>arrivalLocId</c>: the avatar's location is open from the first mount
///     on, <c>applyTileFade</c> at fade 1) — its interior group is visible, its far shell is gone;
///   • the model tiers: <c>building</c> = far ring → low, near → full under 45 m (camera distance minus the
///     footprint's half diagonal, <c>nearBuildingTier</c>), <c>interior</c> = far → low, near → low for an
///     area-detail scene that is not open, else full (<c>nearInteriorTier</c>);
///   • which model specs stand in the overview (<c>mountShell</c>: buildings + OUTDOOR specs, i.e. no room or
///     an outdoor/always-visible room; the indoor ones hang in the interior group, visible only when open);
///   • the far-shell source (<c>shellPlan.farShellSource</c>) with <c>detectStyle</c>/<c>isAreaLocation</c>.
///
/// The browser re-evaluates rings and tiers as its camera moves; the native client builds once, from the
/// bench anchor (= the camera focus the drive keeps: every keyframe targets the anchor) and the start camera.
/// </summary>
public static class LocationView
{
    public const double NearInM = 150, NearOutM = 180, FarPadM = 40, FarOutFactor = 1.2;
    /// <summary><c>FOG_FAR_M</c> (client3d/src/scene/fogConstants.ts).</summary>
    public const double FogFarM = 520;
    public const double BuildingTierNearM = 45, BuildingTierFarM = 60;

    /// <summary><c>ringFor(dist, current = 'gone', pinned, FOG_FAR_M)</c> for a first mount.</summary>
    public static Ring RingFor(double dist, bool pinned)
    {
        if (pinned || dist <= NearInM) return Ring.Near;
        return dist <= FogFarM + FarPadM ? Ring.Far : Ring.Gone;
    }

    /// <summary><c>footprintWidth</c>: the boundary's larger bbox side, else <c>plan_width_m</c>, else 0.</summary>
    public static double FootprintWidth(LocationInfo loc)
    {
        if (loc.Boundary is { Length: >= 3 } b)
            return Math.Max(b.Max(p => p.X) - b.Min(p => p.X), b.Max(p => p.Z) - b.Min(p => p.Z));
        return loc.PlanWidthM > 0 && double.IsFinite(loc.PlanWidthM) ? loc.PlanWidthM : 0;
    }

    /// <summary><c>placeDistance</c>: the smallest footprint distance over the points; 0 inside.</summary>
    public static double PlaceDistance(LocationInfo loc, IEnumerable<(double X, double Z)> points)
    {
        double yaw = loc.YawDeg * Math.PI / 180.0, c = Math.Cos(yaw), s = Math.Sin(yaw);
        double cx = loc.PosX ?? 0, cz = loc.PosZ ?? 0, w = FootprintWidth(loc);
        double best = double.PositiveInfinity;
        foreach (var (x, z) in points)
        {
            double dx = x - cx, dz = z - cz;
            double d = loc.Boundary is { } b ? PolygonDistance(c * dx - s * dz, s * dx + c * dz, b)
                                             : Math.Max(0, Math.Sqrt(dx * dx + dz * dz) - w * Math.Sqrt(0.5));
            best = Math.Min(best, d);
        }
        return best;
    }

    /// <summary><c>pointInPolygon</c> (polygon.ts): half-open ray cast, strict x &lt; crossX.</summary>
    public static bool PointInPolygon(double x, double z, (double X, double Z)[] pts)
    {
        if (pts.Length < 3) return false;
        bool inside = false;
        for (int i = 0, j = pts.Length - 1; i < pts.Length; j = i++)
        {
            var (xi, zi) = pts[i];
            var (xj, zj) = pts[j];
            if ((zi > z) != (zj > z))
            {
                double crossX = (xj - xi) * (z - zi) / (zj - zi) + xi;
                if (x < crossX) inside = !inside;
            }
        }
        return inside;
    }

    /// <summary><c>polygonDistance</c>: 0 inside, else the distance to the nearest edge.</summary>
    public static double PolygonDistance(double x, double z, (double X, double Z)[] pts)
    {
        if (pts.Length < 3) return double.PositiveInfinity;
        if (PointInPolygon(x, z, pts)) return 0;
        double best = double.PositiveInfinity;
        for (int i = 0, j = pts.Length - 1; i < pts.Length; j = i++)
        {
            var (ax, az) = pts[j];
            var (bx, bz) = pts[i];
            double ex = bx - ax, ez = bz - az, len2 = ex * ex + ez * ez;
            double t = len2 > 0 ? Math.Clamp(((x - ax) * ex + (z - az) * ez) / len2, 0, 1) : 0;
            double px = ax + t * ex - x, pz = az + t * ez - z;
            best = Math.Min(best, Math.Sqrt(px * px + pz * pz));
        }
        return best;
    }

    // ── detectStyle / isAreaLocation (tiles.ts) ────────────────────────────

    private static string? TerrainKind(string raw)
    {
        var t = raw.ToLowerInvariant().Trim();
        if (t.Length == 0) return null;
        if (Regex.IsMatch(t, "water|see|lake|meer|ocean|fluss|river|teich|pond")) return "water";
        if (Regex.IsMatch(t, "forest|wald|wood|park")) return "forest";
        if (Regex.IsMatch(t, "road|street|stra|weg|path|asphalt")) return "road";
        if (Regex.IsMatch(t, "grass|wiese|meadow|feld|field|gras")) return "grass";
        return null;
    }

    private static string? StyleKind(string raw)
    {
        var s = raw.ToLowerInvariant().Trim();
        if (s.Length == 0) return null;
        if (Regex.IsMatch(s, "tower|highrise|high-rise|hochhaus|skyscraper")) return "highrise";
        if (Regex.IsMatch(s, "shop|cafe|caf|store|laden|bar|restaurant")) return "cafe";
        if (Regex.IsMatch(s, "house|haus|home|residence|cottage|villa")) return "house";
        if (Regex.IsMatch(s, "generic|hall|block|building")) return "generic";
        return TerrainKind(s);
    }

    /// <summary><c>detectStyle</c>: map3d.style &gt; terrain &gt; the name heuristic.</summary>
    public static string DetectStyle(LocationInfo loc)
    {
        var explicitStyle = StyleKind(loc.Map3dStyle) ?? TerrainKind(loc.Terrain);
        if (explicitStyle is not null) return explicitStyle;
        var n = loc.Name.ToLowerInvariant();
        if (loc.AreaModel)
        {
            if (Regex.IsMatch(n, "forest|wald|park|wood")) return "forest";
            if (Regex.IsMatch(n, "street|stra|road|weg|alley")) return "road";
            return "grass";
        }
        if (Regex.IsMatch(n, "high-rise|highrise|tower|hochhaus|skyscraper|building")) return "highrise";
        if (Regex.IsMatch(n, "caf|bar|restaurant|shop|laden|store|diner")) return "cafe";
        if (Regex.IsMatch(n, "residence|house|haus|home|cottage|villa")) return "house";
        return "generic";
    }

    /// <summary><c>buildPlace</c>: isBuilding = not an area location; natureSite = a building styled as nature.</summary>
    public static (bool IsBuilding, bool NatureSite) Kind(LocationInfo loc)
    {
        bool isBuilding = !loc.AreaModel;
        var style = DetectStyle(loc);
        bool nature = isBuilding && style is "water" or "forest" or "grass" or "road";
        return (isBuilding, nature);
    }

    /// <summary><c>shellPlan.farShellSource</c>: "model" | "recipe" | "ground" | "none".</summary>
    public static string FarShellSource(bool isBuilding, bool natureSite, bool areaDetail, bool hasBuildingModel,
                                        int plates, int walls)
    {
        if (hasBuildingModel) return "model";
        if (!isBuilding || natureSite || areaDetail) return "ground";
        return plates + walls > 0 ? "recipe" : "none";
    }

    /// <summary><c>isOutdoorSpec</c>: no room, or an outdoor / always-visible room.</summary>
    public static bool IsOutdoor(ScenePayload scene, string roomId)
        => roomId.Length == 0 || OutdoorRoomIds(scene).Contains(roomId);

    /// <summary>The rooms that hang straight off the tile (<c>outdoor_rooms</c> ∪ <c>always_visible</c>).</summary>
    public static HashSet<string> OutdoorRoomIds(ScenePayload scene)
    {
        var set = new HashSet<string>(scene.OutdoorRooms);
        foreach (var r in scene.Rooms) if (r.AlwaysVisible) set.Add(r.RoomId);
        return set;
    }

    /// <summary><c>nearBuildingTier</c> from a cold start ('low'): full under 45 m.</summary>
    public static string BuildingTier(Ring ring, double cameraDistanceToCentre, double width)
    {
        if (ring != Ring.Near) return "low";
        double d = cameraDistanceToCentre - width * Math.Sqrt(0.5);
        return d < BuildingTierNearM ? "full" : "low";
    }

    /// <summary><c>wantedInteriorTier</c>: far → low; near → low for a closed area-detail scene, else full.</summary>
    public static string InteriorTier(Ring ring, bool areaDetail, bool open)
        => ring != Ring.Near ? "low" : areaDetail && !open ? "low" : "full";
}
