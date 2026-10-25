using System;
using System.Collections.Generic;
using System.Linq;
using AnimaNative.Scatter;
using AnimaNative.Scene;

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
    public const double NearInM = SceneView.NearInM, NearOutM = SceneView.NearOutM, FarPadM = SceneView.FarPadM,
                        FarOutFactor = SceneView.FarOutFactor;
    /// <summary><c>FOG_FAR_M</c> (client3d/src/scene/fogConstants.ts).</summary>
    public const double FogFarM = 520;
    public const double BuildingTierNearM = 45, BuildingTierFarM = 60;

    /// <summary><c>ringFor(dist, current = 'gone', pinned, FOG_FAR_M)</c> for a first mount (<see cref="SceneView.RingFor"/>).</summary>
    public static Ring RingFor(double dist, bool pinned) => SceneView.RingFor(dist, Ring.Gone, pinned, FogFarM);

    /// <summary><c>footprintWidth</c>: the boundary's larger bbox side, else <c>plan_width_m</c>, else 0.</summary>
    public static double FootprintWidth(LocationInfo loc)
    {
        if (loc.Boundary is { Length: >= 3 } b)
            return Math.Max(b.Max(p => p.X) - b.Min(p => p.X), b.Max(p => p.Z) - b.Min(p => p.Z));
        return loc.PlanWidthM > 0 && double.IsFinite(loc.PlanWidthM) ? loc.PlanWidthM : 0;
    }

    /// <summary>The location as <see cref="SceneView.PlaceDistance"/> reads it (yaw in radians).</summary>
    public static Footprint FootprintOf(LocationInfo loc)
        => new(new P2(loc.PosX ?? 0, loc.PosZ ?? 0), loc.YawDeg * Math.PI / 180.0,
               loc.Boundary?.Select(p => new P2(p.X, p.Z)).ToArray(), FootprintWidth(loc));

    /// <summary><c>placeDistance</c>: the smallest footprint distance over the points; 0 inside.</summary>
    public static double PlaceDistance(LocationInfo loc, IEnumerable<(double X, double Z)> points)
        => SceneView.PlaceDistance(FootprintOf(loc), points.Select(p => new P2(p.X, p.Z)));

    /// <summary><c>pointInPolygon</c> (polygon.ts), see <see cref="SceneView.PointInPolygon"/>.</summary>
    public static bool PointInPolygon(double x, double z, (double X, double Z)[] pts)
        => SceneView.PointInPolygon(x, z, pts.Select(p => new P2(p.X, p.Z)).ToArray());

    /// <summary><c>detectStyle</c> of a location row (<see cref="SceneView.DetectStyle"/>).</summary>
    public static string DetectStyle(LocationInfo loc) => SceneView.DetectStyle(loc.Map3dStyle, loc.AreaModel, loc.Terrain, loc.Name);

    /// <summary><c>buildPlace</c>: isBuilding = not an area location; natureSite = a building styled as nature.</summary>
    public static (bool IsBuilding, bool NatureSite) Kind(LocationInfo loc)
    {
        bool isBuilding = !loc.AreaModel;
        var style = DetectStyle(loc);
        bool nature = isBuilding && style is "water" or "forest" or "grass" or "road";
        return (isBuilding, nature);
    }

    /// <summary><c>isOutdoorSpec</c> over the scene's room lists (<see cref="SceneView.IsOutdoorSpec"/>).</summary>
    public static bool IsOutdoor(ScenePayload scene, string roomId)
        => SceneView.IsOutdoorSpec(roomId, scene.Rooms.Where(r => r.AlwaysVisible).Select(r => r.RoomId).ToList(),
                                   scene.OutdoorRooms.ToList());

    /// <summary>The rooms that hang straight off the tile (<c>outdoor_rooms</c> ∪ <c>always_visible</c>).</summary>
    public static HashSet<string> OutdoorRoomIds(ScenePayload scene)
    {
        var set = new HashSet<string>(scene.OutdoorRooms);
        foreach (var r in scene.Rooms) if (r.AlwaysVisible) set.Add(r.RoomId);
        return set;
    }

    /// <summary>
    /// <c>nearBuildingTier</c> from a cold start ('low'): the distance is the camera's minus the footprint's half
    /// diagonal, the hysteresis is <see cref="SceneView.BuildingTier"/>.
    /// </summary>
    public static string BuildingTier(Ring ring, double cameraDistanceToCentre, double width)
        => BuildingTier(ring, cameraDistanceToCentre, width, "low");

    /// <summary>
    /// <c>wantedBuildingTier</c> at runtime (main.ts <c>tickModelTiers</c>, once a second): far ring → low; near →
    /// <c>buildingTier(|camera − centre| − width·√½, current)</c> — low → full under 45 m, full → low over 60 m, in
    /// between the tier the location shows stays (the 45/60 hysteresis of <see cref="SceneView.BuildingTier"/>).
    /// </summary>
    public static string BuildingTier(Ring ring, double cameraDistanceToCentre, double width, string current)
    {
        if (ring != Ring.Near) return "low";
        return SceneView.BuildingTier(cameraDistanceToCentre - width * Math.Sqrt(0.5), current);
    }

    /// <summary>
    /// <c>SceneLibrary.sweep</c>'s change test: a scene is remounted when its signature moved — a location that gained
    /// or lost its scene (404 ↔ payload) counts as moved (<c>(old?.signature ?? null) !== (fresh?.signature ?? null)</c>).
    /// </summary>
    public static bool SceneChanged(string? mountedSignature, string? freshSignature)
        => !string.Equals(mountedSignature, freshSignature, StringComparison.Ordinal);

    /// <summary><c>wantedInteriorTier</c>: far → low; near → <see cref="SceneView.InteriorTier"/>.</summary>
    public static string InteriorTier(Ring ring, bool areaDetail, bool open)
        => ring != Ring.Near ? "low" : SceneView.InteriorTier(areaDetail, open);
}
