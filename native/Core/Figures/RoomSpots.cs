using System;
using System.Collections.Generic;
using System.Linq;
using AnimaNative.Overview;
using AnimaNative.Scatter;
using AnimaNative.Scene;

namespace AnimaNative.Figures;

/// <summary>The WORLD axis-aligned bounding box of one placed prop (never empty).</summary>
public readonly record struct SpotBox(Vec3 Min, Vec3 Max);

/// <summary>A place marker as the height rule reads it: slot points (world; x/z read), drop, offset, fixed.</summary>
public sealed record SpotMarker(IReadOnlyList<Vec3> Slots, double Drop, double OffsetY, bool Fixed);

/// <summary>What <see cref="RoomSpots.Of"/> derives for one room (all heights world metres).</summary>
public sealed record RoomSpotsResult(RoomRect Rect, P2 CentreLocal, Vec3 Centre, double FloorY,
                                     IReadOnlyList<Vec3> Sit, IReadOnlyList<Vec3> Lie, IReadOnlyList<double?> MarkerY);

/// <summary>
/// THE STANDS OF ONE ROOM — client3d/src/game/roomSpots.ts <c>roomSpotsOf</c> and its rules in game/ground.ts
/// (<c>polygonCentroid</c>, <c>roomSpotGrid</c>, <c>furnitureUse</c> and the constants), checked against
/// shared/test-vectors/room_spots.json.
/// </summary>
public static class RoomSpots
{
    public const double SpotSpread = 0.78;
    public const int SpotGrid = 6;
    public const double SeatMinM = 0.25, SeatMaxM = 0.70;
    public const double LieLengthM = 1.6, LieWidthM = 0.7;

    /// <summary><c>polygonCentroid</c>: the shoelace centre of mass; null under three points or for zero area.</summary>
    public static P2? PolygonCentroid(IReadOnlyList<P2>? poly)
    {
        if (poly is null || poly.Count < 3) return null;
        double twiceArea = 0, cx = 0, cz = 0;
        for (int i = 0; i < poly.Count; i++)
        {
            var (x0, z0) = (poly[i].X, poly[i].Z);
            var (x1, z1) = (poly[(i + 1) % poly.Count].X, poly[(i + 1) % poly.Count].Z);
            double cross = x0 * z1 - x1 * z0;
            twiceArea += cross;
            cx += (x0 + x1) * cross;
            cz += (z0 + z1) * cross;
        }
        if (Math.Abs(twiceArea) < 1e-9) return null;
        return new P2(cx / (3 * twiceArea), cz / (3 * twiceArea));
    }

    /// <summary>
    /// <c>roomSpotGrid(hull, cx, cz, w, d)</c>: the 6 × 6 raster over 0.78 of the box, points outside a hull of three or
    /// more raw points dropped, nearest the centre first (stable on ties, like <c>Array.sort</c>).
    /// </summary>
    public static List<P2> Grid(IReadOnlyList<P2>? hull, double cx, double cz, double w, double d)
    {
        var raw = new List<P2>();
        int n = SpotGrid;
        for (int ix = 0; ix < n; ix++)
        for (int iz = 0; iz < n; iz++)
        {
            double x = cx + ((double)ix / (n - 1) - 0.5) * w * SpotSpread;
            double z = cz + ((double)iz / (n - 1) - 0.5) * d * SpotSpread;
            if (hull is { Count: >= 3 } && !SceneView.PointInPolygon(x, z, hull)) continue;
            raw.Add(new P2(x, z));
        }
        return raw.OrderBy(p => (p.X - cx) * (p.X - cx) + (p.Z - cz) * (p.Z - cz)).ToList();
    }

    /// <summary><c>furnitureUse(floorY, surfaceY, w, d)</c>: "sit" / "lie" / null (no seat).</summary>
    public static string? FurnitureUse(double floorY, double surfaceY, double w, double d)
    {
        double over = surfaceY - floorY;
        if (!(over >= SeatMinM) || !(over <= SeatMaxM)) return null;
        double lng = Math.Max(w, d), shrt = Math.Min(w, d);
        return lng >= LieLengthM && shrt >= LieWidthM ? "lie" : "sit";
    }

    /// <summary>
    /// <c>roomSpotsOf</c>: the rectangle (<see cref="Ambience.RoomRectOf"/>; none = null), the centre (the centroid when
    /// inside the hull, else the raster's first point, else the rectangle's centre) at <paramref name="floorAt"/> +
    /// clearance, the sit / lie surfaces of the props (top middle + clearance), and per marker its height
    /// <c>baseFloorAt(mean slot) − drop + offsetY</c> (null for a fixed marker or one without slots).
    /// <paramref name="floorAt"/> / <paramref name="baseFloorAt"/> take tile-local metres and answer world y.
    /// </summary>
    public static RoomSpotsResult? Of(IReadOnlyList<P2> hull, TileFrame frame, Func<double, double, double> floorAt,
                                      Func<double, double, double> baseFloorAt, IReadOnlyList<SpotBox> props,
                                      IReadOnlyList<SpotMarker> markers)
    {
        if (Ambience.RoomRectOf(hull) is not { } rect) return null;
        var grid = Grid(hull, rect.X, rect.Z, rect.W, rect.D);
        var cen = PolygonCentroid(hull);
        P2? inside = cen is { } c && SceneView.PointInPolygon(c.X, c.Z, hull) ? c : grid.Count > 0 ? grid[0] : null;
        double cx = inside?.X ?? rect.X, cz = inside?.Z ?? rect.Z;
        double floorY = floorAt(cx, cz);
        var w = SceneView.TileToWorld(frame, cx, cz, 0);
        var centre = new Vec3(w.X, floorY + FigureGround.WalkClearanceM, w.Z);

        var sit = new List<Vec3>();
        var lie = new List<Vec3>();
        foreach (var box in props)
        {
            var use = FurnitureUse(floorY, box.Max.Y, box.Max.X - box.Min.X, box.Max.Z - box.Min.Z);
            if (use is null) continue;
            var at = new Vec3((box.Min.X + box.Max.X) / 2, box.Max.Y + FigureGround.WalkClearanceM, (box.Min.Z + box.Max.Z) / 2);
            (use == "lie" ? lie : sit).Add(at);
        }

        var markerY = markers.Select(e =>
        {
            if (e.Fixed || e.Slots.Count == 0) return (double?)null;
            double mx = 0, mz = 0;
            foreach (var s in e.Slots) { mx += s.X; mz += s.Z; }
            var at = SceneView.WorldToTile(frame, mx / e.Slots.Count, mz / e.Slots.Count);
            return baseFloorAt(at.X, at.Z) - e.Drop + e.OffsetY;
        }).ToList();

        return new RoomSpotsResult(rect, new P2(cx, cz), centre, floorY, sit, lie, markerY);
    }
}
