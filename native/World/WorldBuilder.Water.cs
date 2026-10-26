using System;
using System.Collections.Generic;
using System.Linq;
using AnimaNative.Scatter;
using AnimaNative.Scene;
using AnimaNative.Water;
using Godot;

namespace AnimaNative.World;

/// <summary>
/// The water that stands beside the terrain's own (Task 25): the waterfalls of the painted rivers
/// (<see cref="WaterfallLayer"/>), the water sheets of props and dioramas (<see cref="PropWaterSheets"/>) and the
/// underwater ghosts of placed objects (<see cref="SubmergedGhost"/>) — sceneRecipe.ts <c>reliftPlacement</c> /
/// <c>refreshPlacementGhost</c>, worldProps.ts <c>redrapeOne</c> / <c>ghostLevelOf</c>, ground.ts <c>rebuildAreas</c> —
/// and the figures' gate inputs (<see cref="FigureWaterLevel"/>, main.ts <c>groundScopeAt</c> + <c>typeAt</c>).
/// </summary>
public sealed partial class WorldBuilder
{
    /// <summary>The waterfalls of the world (null before the build).</summary>
    public WaterfallLayer? Waterfalls { get; private set; }
    /// <summary>The world props' sheets and ghosts (one record per placed row with either).</summary>
    public List<(SceneModelSpec Spec, Node3D? Node, List<MeshInstance3D> Sheets, SubmergedGhost? Ghost)> WorldPropWater { get; } = new();

    /// <summary>The falls of the ground's terrain payload, rebuilt with every new ground (<c>rebuildAreas</c>).</summary>
    private int RebuildWaterfalls(Node3D root)
    {
        if (Waterfalls is null)
        {
            Waterfalls = new WaterfallLayer();
            root.AddChild(Waterfalls);
        }
        int n = Ground is { } g ? Waterfalls.Rebuild(g.Catalog) : 0;
        if (n > 0)
            _log($"waterfalls: {n} [{string.Join(", ", Waterfalls.Falls.Select(f => $"({f.X:0.#}, {f.Z:0.#}) {f.TopY:0.##} → {f.BottomY:0.##} m, {f.Width:0.#} m wide"))}]");
        return n;
    }

    /// <summary>
    /// The water of one scene placement after its mount, re-lift or tier swap (<c>reliftPlacement</c>'s water half +
    /// <c>refreshPlacementGhost</c>): the sheets are made once and stood at <c>region.y + lift</c> in the placement's
    /// parent; the ghost asks the raster at the base anchor (<c>tileToWorld(anchor, bottom_y + lift)</c>) — level AND
    /// outline (<see cref="WaterGates.PlacementGhostCut"/>). A building is the plot, not something on it: never gated.
    /// </summary>
    private void RefreshPlacementWater(Node3D group, PlacedModel rec, Water.WaterRaster? raster)
    {
        if (rec.IsBuilding) return;
        if (rec.Spec.Water.Length > 0)
        {
            if (rec.WaterSheets is null)
            {
                rec.WaterSheets = PropWaterSheets.Build(rec.Spec.Water, rec.Parent, rec.Lift);
                lock (_waterCounts) _waterCounts.Sheets += rec.WaterSheets.Count;
            }
            else PropWaterSheets.Relift(rec.WaterSheets, rec.Spec.Water, rec.Lift);
        }
        if (rec.Node is not { } node || !GodotObject.IsInstanceValid(node)) return;
        var g = group.Position;
        var frame = new TileFrame(new Overview.Vec3(g.X, g.Y, g.Z), group.Rotation.Y);
        var w = SceneView.TileToWorld(frame, rec.Spec.AnchorX, rec.Spec.AnchorZ);
        double? level = WaterGates.PlacementGhostCut(raster, w.X, w.Z, g.Y + rec.Spec.BottomY + rec.Lift);
        if (rec.Ghost is null)
        {
            // Nothing is built for a dry placement (the browser's red probe).
            if (level is null) return;
            rec.Ghost = new SubmergedGhost(node);
            lock (_waterCounts) _waterCounts.Ghosts++;
        }
        rec.Ghost.Set(level);
    }

    /// <summary>A placement's mesh went (tier swap): its ghost belongs to that mesh and goes with it.</summary>
    private static void DropPlacementGhost(PlacedModel rec)
    {
        rec.Ghost?.Dispose();
        rec.Ghost = null;
    }

    /// <summary>
    /// A world prop's water (<c>redrapeOne</c> + <c>ghostLevelOf</c>): its sheets at <c>region.y + ground(x, z)</c> in the
    /// world frame, its ghost at its bottom over the raster at (x, z).
    /// </summary>
    private void PlaceWorldPropWater(SceneModelSpec spec, Node3D? node, Node3D group, Water.WaterRaster? raster)
    {
        var sheets = spec.Water.Length > 0
            ? PropWaterSheets.Build(spec.Water, group, Height!.GroundAt(spec.AnchorX, spec.AnchorZ))
            : new List<MeshInstance3D>();
        SubmergedGhost? ghost = null;
        if (node is not null && WaterGates.PlacementGhostCut(raster, spec.AnchorX, spec.AnchorZ, spec.BottomY) is { } level)
        {
            ghost = new SubmergedGhost(node);
            ghost.Set(level);
        }
        lock (_waterCounts)
        {
            _waterCounts.Sheets += sheets.Count;
            if (ghost is not null) _waterCounts.Ghosts++;
            if (sheets.Count > 0 || ghost is not null) WorldPropWater.Add((spec, node, sheets, ghost));
        }
    }

    private sealed class WaterCounts { public int Sheets, Ghosts; }
    private readonly WaterCounts _waterCounts = new();

    /// <summary>Prop water sheets made and placement ghosts created so far (the stats line and the check).</summary>
    public (int Sheets, int Ghosts) WaterParts { get { lock (_waterCounts) return (_waterCounts.Sheets, _waterCounts.Ghosts); } }

    /// <summary>
    /// <c>groundScopeAt(x, z)</c> (main.ts): the SMALLEST footprint over the point (<c>tileAt</c>), then the smallest room
    /// rectangle of that place (<c>roomAt</c>) and whether it hangs off the tile (outdoor / always visible) —
    /// <see cref="WaterGates.ScopeOf"/> decides. No footprint = the wilderness.
    /// </summary>
    public GroundScope ScopeAt(double x, double z)
    {
        LocationSlot? best = null;
        double bestArea = 0;
        P2 bestLocal = default;
        foreach (var slot in _slots.Values)
        {
            if (!GodotObject.IsInstanceValid(slot.Group) || slot.Loc.Boundary is not { Length: >= 3 } b) continue;
            var g = slot.Group.Position;
            var p = SceneView.WorldToTile(new TileFrame(new Overview.Vec3(g.X, g.Y, g.Z), slot.Group.Rotation.Y), x, z);
            if (!LocationView.PointInPolygon(p.X, p.Z, b)) continue;
            double area = ScatterMath.PolygonArea(b.Select(q => new P2(q.X, q.Z)).ToList());
            if (best is null || area < bestArea) { best = slot; bestArea = area; bestLocal = p; }
        }
        if (best is null) return GroundScope.Wilderness;
        var room = Ambience.RoomAtRects(best.RoomRects, bestLocal.X, bestLocal.Z);
        bool? roomOutdoor = room is null ? null : best.Storeys.Rooms.TryGetValue(room, out var rg) && rg.Outdoor;
        return WaterGates.ScopeOf(best.Loc.AreaModel, roomOutdoor);
    }

    /// <summary>
    /// The mirror a figure's ghost is gated on (npcs.ts: <c>groundWaterLevel(typeAt(x, z).water_level, scope)</c>): the
    /// topmost painted area's exact profile level at the point, hidden inside a built place. Null = dry.
    /// </summary>
    public double? FigureWaterLevel(double x, double z)
    {
        if (NoWater || Ground is not { } g) return null;
        return WaterGates.GroundWaterLevel(g.Catalog.WaterLevelAt(x, z), ScopeAt(x, z));
    }
}
