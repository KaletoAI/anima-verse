using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.RegularExpressions;
using AnimaNative.Overview;
using AnimaNative.Scatter;
using AnimaNative.World;

namespace AnimaNative.Scene;

/// <summary>The fade-driven looks of an opening location (<c>fadeOpacities</c>).</summary>
public readonly record struct FadeLook(double Roof, double Shell, bool RoofVisible, bool ShellShadow,
                                       bool InteriorVisible, bool LabelsVisible);

/// <summary>Scale, yaw and position of a flat mark (door / boundary).</summary>
public readonly record struct MarkTransform(Vec3 Scale, double Yaw, Vec3 Position);

/// <summary>A neighbouring location as the occlusion test reads it.</summary>
public readonly record struct Neighbour(double X, double Z, double Width, double Height);

/// <summary>A location's frame: the tile centre (world) and its footprint yaw in radians.</summary>
public readonly record struct TileFrame(Vec3 Center, double Yaw);

/// <summary>What the streaming distance reads of a location (<c>FootprintLike</c>); yaw in radians.</summary>
public sealed record Footprint(P2 Center, double Yaw, P2[]? Boundary, double Width);

/// <summary>
/// The pure view decisions of the browser's scene code — what stands, what fades, what turns — ported
/// from client3d/src/scene/sceneView.ts (and the re-exported storeyDisplay.ts, shellPlan.ts,
/// game/streamRings.ts, game/polygon.ts), checked against shared/test-vectors/scene_view.json.
/// </summary>
public static class SceneView
{
    public const double NearInM = 150, NearOutM = 180, FarPadM = 40, FarOutFactor = 1.2;

    /// <summary><c>openable</c>: an interior, and a building or a shell-area / ground model.</summary>
    public static bool Openable(bool interior, bool isBuilding, bool modelIsShellArea = false, bool modelIsGround = false)
        => interior && (isBuilding || modelIsShellArea || modelIsGround);

    /// <summary><c>hasInterior</c>: any plate, floor-plan room, wall, extra, marker, or a non-building model.</summary>
    public static bool HasInterior(int plates, int floorPlan, int walls, int extras, int markers, IEnumerable<string?> modelRoles)
        => plates > 0 || floorPlan > 0 || walls > 0 || extras > 0 || markers > 0 || modelRoles.Any(r => r != "building");

    /// <summary><c>isOutdoorSpec</c>: no room, or an always-visible / outdoor room.</summary>
    public static bool IsOutdoorSpec(string? roomId, IReadOnlyCollection<string> alwaysVisible, IReadOnlyCollection<string> outdoor)
        => string.IsNullOrEmpty(roomId) || alwaysVisible.Contains(roomId) || outdoor.Contains(roomId);

    /// <summary><c>buildingTier</c>: low → full under 45 m, full → low over 60 m, in between it stays.</summary>
    public static string BuildingTier(double distance, string current)
    {
        if (current == "low" && distance < 45) return "full";
        if (current == "full" && distance > 60) return "low";
        return current;
    }

    /// <summary><c>interiorTier</c>: a closed area-detail scene stays low.</summary>
    public static string InteriorTier(bool areaDetail, bool open) => areaDetail && !open ? "low" : "full";

    /// <summary><c>wallVisible</c>: the camera is not on the outer side, and the wall is on the shown storey.</summary>
    public static bool WallVisible(double camX, double camZ, double midX, double midZ, double normalX, double normalZ,
                                   double level, double shown)
        => (camX - midX) * normalX + (camZ - midZ) * normalZ <= 0 && level == shown;

    /// <summary><c>fadeStep</c>: exponential approach, three's lerp operation order.</summary>
    public static double FadeStep(double fade, double target, double dt)
    {
        double k = 1 - Math.Exp(-4 * dt);
        return (1 - k) * fade + k * target;
    }

    public static FadeLook FadeOpacities(double f)
        => new(Math.Max(0, 1 - f * 1.4), 1 - f * 0.88, f < 0.95, f < 0.4, f > 0.03, f > 0.5);

    /// <summary>A neighbour whose occlusion fade reached this is hidden outright (<c>group.visible = occl &lt; 0.95</c>).</summary>
    public const double OccludedHideAt = 0.95;

    /// <summary>
    /// <c>applyTileOcclusion</c>'s step (client3d/src/scene/tiles.ts, inline there — no vector): three's
    /// <c>MathUtils.lerp(occl, hide ? 1 : 0, 1 − e^(−8·dt))</c>, snapped to 0 below 0.02 once nothing hides it;
    /// a tile at 0 that nothing hides stays 0 (the early return).
    /// </summary>
    public static double OcclusionStep(double occl, bool hide, double dt)
    {
        if (occl == 0 && !hide) return 0;
        double t = 1 - Math.Exp(-8 * dt);
        double v = (1 - t) * occl + t * (hide ? 1 : 0);
        return v < 0.02 && !hide ? 0 : v;
    }

    /// <summary>
    /// Godot's <c>FADE_ALPHA_PASS_THRESHOLD</c> (servers/rendering/renderer_rd/forward_clustered/
    /// render_forward_clustered.cpp): an instance whose fade alpha (1 − transparency) is below 0.999 is drawn in the
    /// transparent pass, at or above it in the opaque pass.
    /// </summary>
    public const double OpaqueFadeAlpha = 0.999;

    /// <summary>
    /// The native form of the two material opacities the browser writes (the roof fade <c>m.opacity = roof</c>
    /// and the occlusion <c>opacity = base·(1 − occl)</c>): ONE instance transparency per mesh,
    /// 1 − <paramref name="opacity"/>·(1 − <paramref name="occl"/>), the material's own opacity left to the material
    /// (Godot multiplies the two). Values the renderer would draw opaque anyway (fade alpha ≥ 0.999) are 0, so an
    /// opaque mesh goes back to the opaque pass the moment the fade lets it.
    /// </summary>
    public static double InstanceTransparency(double opacity, double occl)
    {
        double alpha = Math.Clamp(opacity, 0, 1) * (1 - Math.Clamp(occl, 0, 1));
        return alpha >= OpaqueFadeAlpha ? 0 : 1 - alpha;
    }

    /// <summary><c>roomVisible</c>: always-visible, or on the shown storey (no level = 0).</summary>
    public static bool RoomVisible(bool alwaysVisible, double? level, double shown) => alwaysVisible || (level ?? 0) == shown;

    /// <summary><c>storeyPieceOpacity</c>: the shown storey solid, every other one its composed ghost.</summary>
    public static double StoreyPieceOpacity(double pieceLevel, double shownLevel, double ghost)
        => pieceLevel == shownLevel ? 1 : ghost;

    /// <summary><c>farShellSource</c>: "model" | "ground" | "recipe" | "none".</summary>
    public static string FarShellSource(bool isBuilding, bool natureSite, bool areaDetail, bool hasBuildingModel,
                                        double plates, double walls)
    {
        if (hasBuildingModel) return "model";
        if (!isBuilding || natureSite || areaDetail) return "ground";
        double primitives = (double.IsFinite(plates) ? plates : 0) + (double.IsFinite(walls) ? walls : 0);
        return primitives > 0 ? "recipe" : "none";
    }

    /// <summary><c>farShellPiece</c>: at or above ground; a storey plate (no room), a non-glass wall.</summary>
    public static bool FarShellPiece(string kind, double level, string? roomId, bool glass)
        => level >= 0 && (kind == "plate" ? string.IsNullOrEmpty(roomId) : !glass);

    public static MarkTransform DoorMarkTransform(double width, double thickness, P2 along, P2 mid, double baseY)
        => new(new Vec3(width, 1, Math.Max(width * 0.3, thickness)), Math.Atan2(-along.Z, along.X), new Vec3(mid.X, baseY + 0.02, mid.Z));

    public static MarkTransform BoundaryMarkTransform(double width, P2 inward, double x, double z, double ground)
        => new(new Vec3(width, 1, Math.Max(width * 0.3, 0.3)), Math.Atan2(inward.X, inward.Z), new Vec3(x, ground + 0.05, z));

    /// <summary><c>neighbourOccludes</c>: a tall neighbour near the camera→target line, between 5 % and 92 % of it.</summary>
    public static bool NeighbourOccludes(P2 camera, P2 target, Neighbour neighbour, bool sameTile = false)
    {
        if (sameTile || neighbour.Height <= 1.5) return false;
        double tx = target.X - camera.X, tz = target.Z - camera.Z;
        double nx = neighbour.X - camera.X, nz = neighbour.Z - camera.Z;
        double len2 = tx * tx + tz * tz;
        double t = len2 > 1e-6 ? (nx * tx + nz * tz) / len2 : 0;
        double px = camera.X + tx * t, pz = camera.Z + tz * t;
        return t > 0.05 && t < 0.92 && double.Hypot(neighbour.X - px, neighbour.Z - pz) < neighbour.Width * 1.05;
    }

    /// <summary><c>basementHole</c>: grow only the camera-facing edges, by at most one footprint width. [minX, minZ, maxX, maxZ].</summary>
    public static double[] BasementHole(BoundsXZ bounds, P2 center, P2 camera, double width)
    {
        double minX = bounds.MinX, minZ = bounds.MinZ, maxX = bounds.MaxX, maxZ = bounds.MaxZ;
        double dx = camera.X - center.X, dz = camera.Z - center.Z;
        double len = Js.Or(double.Hypot(dx, dz), 1), ux = dx / len, uz = dz / len;
        if (ux > 0) maxX += width * ux; else minX += width * ux;
        if (uz > 0) maxZ += width * uz; else minZ += width * uz;
        return new[] { minX, minZ, maxX, maxZ };
    }

    /// <summary><c>tileToWorld</c>: a tile-local point into the world (rotation.y = +yaw, § A1.1).</summary>
    public static Vec3 TileToWorld(TileFrame tile, double lx, double lz, double ly = 0)
    {
        double c = Math.Cos(tile.Yaw), s = Math.Sin(tile.Yaw);
        return new Vec3(tile.Center.X + lx * c + lz * s, tile.Center.Y + ly, tile.Center.Z - lx * s + lz * c);
    }

    /// <summary>
    /// <c>worldToTile</c> (tiles.ts → scene-render <c>worldToLocalXZ</c>): a world (x, z) into the tile frame, the inverse
    /// of <see cref="TileToWorld"/> (a turn by −yaw); checked against shared/test-vectors/ambience.json [T].
    /// </summary>
    public static P2 WorldToTile(TileFrame tile, double x, double z)
    {
        double c = Math.Cos(tile.Yaw), s = Math.Sin(tile.Yaw);
        double dx = x - tile.Center.X, dz = z - tile.Center.Z;
        return new P2(dx * c - dz * s, dx * s + dz * c);
    }

    public static P2 TileDirToWorld(double yaw, double lx, double lz)
    {
        double c = Math.Cos(yaw), s = Math.Sin(yaw);
        return new P2(lx * c + lz * s, -lx * s + lz * c);
    }

    /// <summary><c>tileWorldBounds</c>: the world xz bounds of the turned boundary; null without one.</summary>
    public static BoundsXZ? TileWorldBounds(TileFrame tile, IReadOnlyList<P2>? boundary)
    {
        if (boundary is null) return null;
        double minX = double.PositiveInfinity, minZ = double.PositiveInfinity, maxX = double.NegativeInfinity, maxZ = double.NegativeInfinity;
        foreach (var b in boundary)
        {
            var p = TileToWorld(tile, b.X, b.Z);
            if (p.X < minX) minX = p.X;
            if (p.X > maxX) maxX = p.X;
            if (p.Z < minZ) minZ = p.Z;
            if (p.Z > maxZ) maxZ = p.Z;
        }
        return new BoundsXZ(minX, maxX, minZ, maxZ);
    }

    // ---- detectStyle (tiles.ts) ------------------------------------------------------------------

    private static string Lower(string? s) => (s ?? "").ToLowerInvariant();

    private static string? TerrainKind(string? raw)
    {
        var t = JsTrim(Lower(raw));
        if (t.Length == 0) return null;
        if (Regex.IsMatch(t, "water|see|lake|meer|ocean|fluss|river|teich|pond")) return "water";
        if (Regex.IsMatch(t, "forest|wald|wood|park")) return "forest";
        if (Regex.IsMatch(t, "road|street|stra|weg|path|asphalt")) return "road";
        if (Regex.IsMatch(t, "grass|wiese|meadow|feld|field|gras")) return "grass";
        return null;
    }

    private static string? StyleKind(string? raw)
    {
        var s = JsTrim(Lower(raw));
        if (s.Length == 0) return null;
        if (Regex.IsMatch(s, "tower|highrise|high-rise|hochhaus|skyscraper")) return "highrise";
        if (Regex.IsMatch(s, "shop|cafe|caf|store|laden|bar|restaurant")) return "cafe";
        if (Regex.IsMatch(s, "house|haus|home|residence|cottage|villa")) return "house";
        if (Regex.IsMatch(s, "generic|hall|block|building")) return "generic";
        return TerrainKind(s);
    }

    private static string JsTrim(string s)
    {
        int a = 0, b = s.Length;
        while (a < b && JsSemantics.IsWhiteSpace(s[a])) a++;
        while (b > a && JsSemantics.IsWhiteSpace(s[b - 1])) b--;
        return s.Substring(a, b - a);
    }

    /// <summary><c>detectStyle</c>: map3d.style &gt; terrain &gt; the name heuristic (area vocabulary only for an area).</summary>
    public static string DetectStyle(string? map3dStyle, bool areaModel, string? terrain, string? name)
    {
        var explicitStyle = StyleKind(map3dStyle) ?? TerrainKind(terrain);
        if (explicitStyle is not null) return explicitStyle;
        var n = Lower(name);
        if (areaModel)
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

    // ---- streaming rings (streamRings.ts, polygon.ts) ---------------------------------------------

    /// <summary><c>ringFor</c> with its hysteresis: near in at 150 m, out at 180 m; far within fog + 40 m (× 1.2 to leave).</summary>
    public static Ring RingFor(double dist, Ring current, bool pinned, double fogM)
    {
        if (pinned || dist <= (current == Ring.Near ? NearOutM : NearInM)) return Ring.Near;
        return dist <= (fogM + FarPadM) * (current == Ring.Gone ? 1 : FarOutFactor) ? Ring.Far : Ring.Gone;
    }

    /// <summary><c>placeDistance</c>: the smallest footprint distance over the points; 0 inside.</summary>
    public static double PlaceDistance(Footprint p, IEnumerable<P2> points)
    {
        double c = Math.Cos(p.Yaw), s = Math.Sin(p.Yaw);
        double best = double.PositiveInfinity;
        foreach (var point in points)
        {
            double dx = point.X - p.Center.X, dz = point.Z - p.Center.Z;
            double d = p.Boundary is { } b ? PolygonDistance(c * dx - s * dz, s * dx + c * dz, b)
                                           : Math.Max(0, double.Hypot(dx, dz) - p.Width * Math.Sqrt(0.5));
            best = Math.Min(best, d);
        }
        return best;
    }

    /// <summary><c>sanitizePolygon</c>: a closing duplicate dropped, null under 3 points or with a non-finite one.</summary>
    public static P2[]? SanitizePolygon(IReadOnlyList<P2>? points)
    {
        var pts = new List<P2>();
        foreach (var p in points ?? Array.Empty<P2>())
        {
            if (!double.IsFinite(p.X) || !double.IsFinite(p.Z)) return null;
            pts.Add(p);
        }
        if (pts.Count >= 2 && pts[0].X == pts[^1].X && pts[0].Z == pts[^1].Z) pts.RemoveAt(pts.Count - 1);
        return pts.Count >= 3 ? pts.ToArray() : null;
    }

    /// <summary><c>pointInPolygon</c>: half-open ray cast, strict x &lt; crossX.</summary>
    public static bool PointInPolygon(double x, double z, IReadOnlyList<P2>? points)
    {
        var pts = SanitizePolygon(points);
        if (pts is null) return false;
        bool inside = false;
        for (int i = 0, j = pts.Length - 1; i < pts.Length; j = i++)
        {
            var (xi, zi) = (pts[i].X, pts[i].Z);
            var (xj, zj) = (pts[j].X, pts[j].Z);
            if ((zi > z) != (zj > z))
            {
                double crossX = (xj - xi) * (z - zi) / (zj - zi) + xi;
                if (x < crossX) inside = !inside;
            }
        }
        return inside;
    }

    private static double PointSegmentDistance(double px, double pz, double ax, double az, double bx, double bz)
    {
        double dx = bx - ax, dz = bz - az;
        double len2 = dx * dx + dz * dz;
        if (len2 < 1e-18) return double.Hypot(px - ax, pz - az);
        double t = ((px - ax) * dx + (pz - az) * dz) / len2;
        t = Math.Max(0, Math.Min(1, t));
        return double.Hypot(px - (ax + t * dx), pz - (az + t * dz));
    }

    /// <summary><c>polygonDistance</c>: 0 inside, else the distance to the nearest edge; ∞ without a polygon.</summary>
    public static double PolygonDistance(double x, double z, IReadOnlyList<P2>? points)
    {
        var pts = SanitizePolygon(points);
        if (pts is null) return double.PositiveInfinity;
        if (PointInPolygon(x, z, pts)) return 0;
        double best = double.PositiveInfinity;
        for (int i = 0, j = pts.Length - 1; i < pts.Length; j = i++)
            best = Math.Min(best, PointSegmentDistance(x, z, pts[j].X, pts[j].Z, pts[i].X, pts[i].Z));
        return best;
    }
}
