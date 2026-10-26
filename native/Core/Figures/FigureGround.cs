using System;
using System.Collections.Generic;
using AnimaNative.Scatter;
using AnimaNative.Scene;

namespace AnimaNative.Figures;

/// <summary>How a non-travelling character is placed (<c>placementOf</c>): by its tile, at a free point, or not at all.</summary>
public enum PlacementKind { Tile, Free, Offmap }

/// <summary>The answer of <see cref="FigureGround.PlacementOf"/>; <see cref="Pos"/> only for <see cref="PlacementKind.Free"/>.</summary>
public readonly record struct Placement(PlacementKind Kind, P2? Pos);

/// <summary>What a figure has to do to get from its last placement to the next one (<c>figureTransition</c>).</summary>
public enum FigureTransition { Snap, Route, Stay }

/// <summary>Where a figure was drawn last time: the room (null = on the ground) and whether the interior was revealed.</summary>
public readonly record struct ShownPlacement(string? Room, bool InteriorShown);

/// <summary>One floor plate of the recipe as the walk rule reads it: <c>top_y</c>, outline and openings, tile-local.</summary>
public sealed record WalkPlate(double Top, IReadOnlyList<P2> Outline, IReadOnlyList<IReadOnlyList<P2>>? Holes = null);

/// <summary>A room's DECLARED walking floor (<c>walk_y_world</c> of its diorama + the room hull), tile-local.</summary>
public sealed record DeclaredFloor(string RoomId, double Top, IReadOnlyList<P2> Outline);

/// <summary>
/// The figure ground rules of the browser, pure — client3d/src/game/placement.ts (<c>placementOf</c>,
/// <c>figureTransition</c>, <c>pollIsStale</c>), game/walk.ts (<c>gateStandY</c>) and game/ground.ts (<c>standY</c>,
/// <c>tileWalkLadder</c>, <c>roomFloorLadder</c>, <c>roomStandLadder</c>, <c>recipeFloorAt</c>, <c>declaredFloorAt</c>,
/// <c>plateCeiling</c>). Checked against shared/test-vectors/figure_ground.json, room_spots.json, place_poll.json; the
/// three floor rungs (<c>recipeFloorAt</c>, <c>declaredFloorAt</c>, <c>plateCeiling</c>) have no shared vector yet and
/// are held to the hand cases of client3d/scripts/smoke_walk_math.mjs in tests/FigureGroundRungTests.cs.
/// </summary>
public static class FigureGround
{
    /// <summary><c>WALK_CLEARANCE_M</c>: the hair a sole stands above the surface it was measured on.</summary>
    public const double WalkClearanceM = 0.01;
    /// <summary><c>ROOF_CLEARANCE_M</c>: over the model's declared standing height a plate belongs to the next storey.</summary>
    public const double RoofClearanceM = 1.2;

    /// <summary><c>placementOf(hasTile, pos)</c>: the tile places it; else a finite point is a free figure; else offmap.</summary>
    public static Placement PlacementOf(bool hasTile, double? x, double? z)
    {
        if (hasTile) return new Placement(PlacementKind.Tile, null);
        if (x is { } px && z is { } pz && double.IsFinite(px) && double.IsFinite(pz))
            return new Placement(PlacementKind.Free, new P2(px, pz));
        return new Placement(PlacementKind.Offmap, null);
    }

    /// <summary>
    /// <c>figureTransition(prev, next)</c>: no previous placement = snap; the same drawn room = stay; a view change
    /// (interior revealed / hidden) = snap; otherwise a real room change = route.
    /// </summary>
    public static FigureTransition Transition(ShownPlacement? prev, ShownPlacement next)
    {
        if (prev is not { } p) return FigureTransition.Snap;
        if (p.Room == next.Room) return FigureTransition.Stay;
        if (p.InteriorShown != next.InteriorShown) return FigureTransition.Snap;
        return FigureTransition.Route;
    }

    /// <summary><c>pollIsStale(polledAt, ownChangeAt)</c>: a poll asked before our own seat change was answered.</summary>
    public static bool PollIsStale(double polledAt, double ownChangeAt) => polledAt < ownChangeAt;

    /// <summary>
    /// <c>gateStandY(baked, declared, terrain)</c>: the lattice (else the declaration), floored by the terrain; a
    /// non-finite rung falls through, a non-finite terrain leaves the lattice alone. null = the rung is silent.
    /// </summary>
    public static double GateStandY(double? baked, double? declared, double terrain)
    {
        double lattice = baked is { } b && double.IsFinite(b) ? b
            : declared is { } d && double.IsFinite(d) ? d : double.NaN;
        if (!double.IsFinite(lattice)) return terrain;
        return double.IsFinite(terrain) ? Math.Max(lattice, terrain) : lattice;
    }

    /// <summary>
    /// <c>standY(walkY, terrainY)</c>: the higher of the tile's and the world's answer; a non-finite tile answer reads
    /// as 0, a non-finite world answer leaves the tile answer.
    /// </summary>
    public static double StandY(double walkY, double terrainY)
    {
        double walk = double.IsFinite(walkY) ? walkY : 0;
        double terrain = double.IsFinite(terrainY) ? terrainY : walk;
        return Math.Max(walk, terrain);
    }

    /// <summary>
    /// <c>tileWalkLadder(datumY, baked, declared, plate)</c>: the first rung that answers — the baked lattice (world)
    /// + clearance, a declaration over the datum + clearance, a storey plate over the datum + clearance — else the datum.
    /// </summary>
    public static double TileWalkLadder(double datumY, double? baked, double? declared, double? plate)
    {
        if (baked is { } b) return b + WalkClearanceM;
        if (declared is { } d) return datumY + d + WalkClearanceM;
        if (plate is { } p) return datumY + p + WalkClearanceM;
        return datumY;
    }

    /// <summary>
    /// <c>roomFloorLadder(datumY, baked, declared, terrain)</c>: the room's lattice, else datum + its declaration, else
    /// a finite terrain, else the datum. <paramref name="declared"/> null = undefined.
    /// </summary>
    public static double RoomFloorLadder(double datumY, double? baked, double? declared, double terrain)
    {
        if (baked is { } b) return b;
        if (declared is { } d) return datumY + d;
        return double.IsFinite(terrain) ? terrain : datumY;
    }

    /// <summary><c>roomStandLadder(floorY, centreY)</c>: the floor + clearance, else the stand centre's height, else null.</summary>
    public static double? RoomStandLadder(double? floorY, double? centreY)
    {
        if (floorY is { } f) return f + WalkClearanceM;
        return centreY;
    }

    /// <summary>
    /// <c>recipeFloorAt(plates, lx, lz, ceiling)</c>: the highest plate below <paramref name="ceiling"/> whose outline
    /// holds the point and none of whose holes does; null where none answers.
    /// </summary>
    public static double? RecipeFloorAt(IEnumerable<WalkPlate>? plates, double lx, double lz, double ceiling)
    {
        double? best = null;
        foreach (var plate in plates ?? Array.Empty<WalkPlate>())
        {
            if (!(plate.Top < ceiling)) continue;
            if (best is { } b && plate.Top <= b) continue;
            if (!SceneView.PointInPolygon(lx, lz, plate.Outline)) continue;
            bool inHole = false;
            if (plate.Holes is { } holes)
                foreach (var ring in holes)
                    if (SceneView.PointInPolygon(lx, lz, ring)) { inHole = true; break; }
            if (inHole) continue;
            best = plate.Top;
        }
        return best;
    }

    /// <summary>
    /// <c>declaredFloorAt(floors, lx, lz)</c>: the declaration whose hull holds the point; where several do, the smallest
    /// positive area wins (the first one on a tie); a non-finite top never declares. null where none answers.
    /// </summary>
    public static double? DeclaredFloorAt(IEnumerable<DeclaredFloor>? floors, double lx, double lz)
    {
        DeclaredFloor? best = null;
        double bestArea = -1;
        foreach (var floor in floors ?? Array.Empty<DeclaredFloor>())
        {
            if (!double.IsFinite(floor.Top)) continue;
            if (!SceneView.PointInPolygon(lx, lz, floor.Outline)) continue;
            if (best is null) { best = floor; continue; }
            if (bestArea < 0) bestArea = Area(best.Outline);
            double area = Area(floor.Outline);
            if (area > 0 && (bestArea <= 0 || area < bestArea))
            {
                best = floor;
                bestArea = area;
            }
        }
        return best?.Top;
    }

    /// <summary>
    /// <c>plateCeiling(info)</c>: one roof clearance over the model's declared standing height (a non-finite or absent
    /// one counts as 0) — the same for every display since E5b, so only <c>walk_y_world</c> is read.
    /// </summary>
    public static double PlateCeiling(double? modelWalkY)
        => (modelWalkY is { } w && double.IsFinite(w) ? w : 0) + RoofClearanceM;

    /// <summary>game/polygon.ts <c>polygonArea</c>: |shoelace| of the sanitised ring, 0 for a degenerate one.</summary>
    private static double Area(IReadOnlyList<P2> outline)
        => SceneView.SanitizePolygon(outline) is { } pts ? ScatterMath.PolygonArea(pts) : 0;
}
