using System;
using System.Collections.Generic;
using System.Linq;
using AnimaNative.Figures;
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

    /// <summary>The world props that carry water regions (worldProps.ts <c>waterAt</c> reads every row, culled or not).</summary>
    private readonly List<SceneModelSpec> _worldPropWaterSpecs = new();

    /// <summary>
    /// main.ts <c>tileAt(x, z)</c>: the SMALLEST mounted footprint over the point, with the point in its tile frame; null
    /// out between the places.
    /// </summary>
    private (LocationSlot Slot, P2 Local)? TileAt(double x, double z)
    {
        // Every walking figure asks this a few times a frame: no allocation, the area by the shoelace loop.
        LocationSlot? best = null;
        double bestArea = 0;
        P2 bestLocal = default;
        foreach (var slot in _slots.Values)
        {
            if (!GodotObject.IsInstanceValid(slot.Group) || slot.Loc.Boundary is not { Length: >= 3 } b) continue;
            var g = slot.Group.Position;
            var p = SceneView.WorldToTile(new TileFrame(new Overview.Vec3(g.X, g.Y, g.Z), slot.Group.Rotation.Y), x, z);
            if (!LocationView.PointInPolygon(p.X, p.Z, b)) continue;
            double twice = 0;
            for (int i = 0, j = b.Length - 1; i < b.Length; j = i++) twice += b[j].X * b[i].Z - b[i].X * b[j].Z;
            double area = Math.Abs(twice) / 2;
            if (best is null || area < bestArea) { best = slot; bestArea = area; bestLocal = p; }
        }
        return best is null ? null : (best, bestLocal);
    }

    /// <summary>
    /// <c>groundScopeAt(x, z)</c> (main.ts): the SMALLEST footprint over the point (<c>tileAt</c>), then the smallest room
    /// rectangle of that place (<c>roomAt</c>) and whether it hangs off the tile (outdoor / always visible) —
    /// <see cref="WaterGates.ScopeOf"/> decides. No footprint = the wilderness.
    /// </summary>
    public GroundScope ScopeAt(double x, double z) => ScopeIn(TileAt(x, z));

    private static GroundScope ScopeIn((LocationSlot Slot, P2 Local)? tile)
    {
        if (tile is not { } t) return GroundScope.Wilderness;
        var room = Ambience.RoomAtRects(t.Slot.RoomRects, t.Local.X, t.Local.Z);
        bool? roomOutdoor = room is null ? null : t.Slot.Storeys.Rooms.TryGetValue(room, out var rg) && rg.Outdoor;
        return WaterGates.ScopeOf(t.Slot.Loc.AreaModel, roomOutdoor);
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

    /// <summary>
    /// main.ts <c>groundY(x, z)</c>, the ONE height sampler of every figure: inside a footprint the tile ladder
    /// (<c>tileGroundY</c>, which already answers the higher of the tile and the world), outside the world height.
    /// </summary>
    public double FigureGroundY(double x, double z)
        => TileAt(x, z) is { } t ? t.Slot.Stands.TileGroundY(x, z) : Height?.GroundAt(x, z) ?? 0;

    /// <summary>
    /// main.ts <c>setTerrainMove</c>: what the ground says at a world point for the walking figure — ground.ts
    /// <c>typeAt</c> (movement word, sinks, mirror, swim threshold, speed), the scope (<see cref="ScopeAt"/>) and a prop
    /// water region over the point (<see cref="PropWaterAt"/>) carrying the gate bed it is measured against
    /// (<see cref="GateBedAt"/>).
    /// </summary>
    public GroundMove FigureGroundMove(double x, double z)
    {
        var tile = TileAt(x, z);
        var type = Ground?.Catalog.TypeAt(x, z);
        var pw = PropWaterAt(x, z, tile);
        return new GroundMove(type?.Movement ?? Figures.FigureClips.WalkRun,
                              new GroundSink(type?.MoveSinkM ?? 0, type?.IdleSinkM ?? 0), type?.WaterLevel,
                              type?.SwimFromM ?? WaterGates.SwimFromDefaultM, type?.SpeedFactor ?? 1, ScopeIn(tile),
                              pw is { } hit ? hit with { GroundY = GateBedAt(x, z, tile) } : null);
    }

    /// <summary>
    /// main.ts <c>propWaterAt(x, z, tile)</c>: the world props' regions (lift = the ground at the prop), then the storey-0
    /// placements of the tile in its frame (lift = the placement's lift + the datum) — the higher mirror wins.
    /// </summary>
    public WaterHit? PropWaterAt(double x, double z) => PropWaterAt(x, z, TileAt(x, z));

    private WaterHit? PropWaterAt(double x, double z, (LocationSlot Slot, P2 Local)? tile)
    {
        WaterHit? hit;
        lock (_worldPropWaterSpecs)
            hit = _worldPropWaterSpecs.Count == 0 ? null
                : PropWater.WaterRegionAt(_worldPropWaterSpecs, x, z, spec => Height?.GroundAt(spec.AnchorX, spec.AnchorZ) ?? 0);
        if (tile is not { } t) return hit;
        bool wet = false;
        foreach (var rec in t.Slot.Placements) wet |= rec.Spec.Level == 0 && rec.Spec.Water.Length > 0;
        if (!wet) return hit;
        var placements = t.Slot.Placements.Where(rec => rec.Spec.Level == 0).ToList();
        var lifts = placements.GroupBy(rec => rec.Spec).ToDictionary(g => g.Key, g => g.Last().Lift);
        double datum = t.Slot.Group.Position.Y;
        var region = PropWater.WaterRegionAt(placements.Select(rec => rec.Spec), t.Local.X, t.Local.Z,
                                             spec => (lifts.TryGetValue(spec, out var l) ? l : 0) + datum);
        if (region is { } r && (hit is not { } h || r.Y > h.Y)) hit = r;
        return hit;
    }

    /// <summary>
    /// main.ts <c>gateBedAt(x, z, tile)</c>: where the height gate measures a figure — the terrain, the tile's storey-0
    /// lattices and its storey-0 declared floors (<c>groundStoreyFloors</c>) through <see cref="Figures.FigureGround.GateStandY"/>.
    /// </summary>
    private double GateBedAt(double x, double z, (LocationSlot Slot, P2 Local)? tile)
    {
        double terrain = Height?.GroundAt(x, z) ?? 0;
        if (tile is not { } t) return terrain;
        var st = t.Slot.Stands;
        var baked = st.BakedFloorAt(t.Local.X, t.Local.Z, e => e.Level == 0);
        double? declared = st.DeclaredFloors.Count > 0
            ? Figures.FigureGround.DeclaredFloorAt(
                st.DeclaredFloors.Where(f => (st.RoomLevels.TryGetValue(f.RoomId, out var l) ? l : 0) == 0), t.Local.X, t.Local.Z)
            : null;
        return Figures.FigureGround.GateStandY(baked, declared is { } d ? t.Slot.Group.Position.Y + d : null, terrain);
    }
}
