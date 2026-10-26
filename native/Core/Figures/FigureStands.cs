using System;
using System.Collections.Generic;
using System.Linq;
using AnimaNative.Overview;
using AnimaNative.Scatter;
using AnimaNative.Scene;

namespace AnimaNative.Figures;

/// <summary>One room's floor as data (tiles.ts <c>RoomFloor</c>): its hull (tile-local) and the declared height over the datum.</summary>
public sealed class RoomFloor
{
    public required IReadOnlyList<P2> Hull { get; init; }
    /// <summary>Tile-local over the datum; null = undeclared (the terrain is the floor).</summary>
    public double? Declared { get; set; }
}

/// <summary>
/// THE GROUND AND THE STANDS OF ONE MOUNTED LOCATION for its figures — the browser's tile fields the placement reads
/// (client3d/src/scene/tiles.ts <c>tileGroundY</c>/<c>tileWalkY</c>, <c>bakedFloorAt</c>, <c>roomFloorWorldY</c>,
/// <c>roomBaseFloorY</c>, <c>roomFloorAt</c>, <c>roomStandY</c>, <c>deriveRoomSpots</c>, <c>deriveCorridorCentres</c>)
/// over the vector-checked rules of <see cref="FigureGround"/> and <see cref="RoomSpots"/>. The lookups are filled by the
/// mount (surfaces, declared floors, plates, room floors, room levels, the always-visible rooms, the corridors) and the
/// derived maps (<see cref="RoomCenters"/>, <see cref="SitSpots"/>, <see cref="LieSpots"/>, <see cref="RoomRects"/>)
/// by <see cref="DeriveAll"/>, after the mount and after every re-lift. Hand cases: tests/FigureStandsTests.cs.
/// </summary>
public sealed class FigureStands
{
    /// <summary>The tile frame (centre on the datum, yaw in radians); the re-datum moves it.</summary>
    public TileFrame Frame { get; set; }
    /// <summary>The world ground (NaN = nothing to say yet).</summary>
    public Func<double, double, double>? WorldGround { get; set; }

    /// <summary><c>tile.surfaces</c>: the baked lattices with the lift their placement carries now.</summary>
    public List<PlacedSurface> Surfaces { get; } = new();
    /// <summary><c>tile.declaredFloors</c>: the rooms' declared walking floors (diorama <c>walk_y_world</c> + lift).</summary>
    public List<DeclaredFloor> DeclaredFloors { get; } = new();
    /// <summary><c>tile.walkPlates</c>: the recipe's plates (declared storeys).</summary>
    public List<WalkPlate> WalkPlates { get; } = new();
    /// <summary><c>tile.modelWalkY</c>: the building model's <c>walk_y_world</c>.</summary>
    public double? ModelWalkY { get; set; }
    /// <summary><c>tile.roomFloors</c>, in insertion order (the derive order).</summary>
    public List<KeyValuePair<string, RoomFloor>> RoomFloors { get; } = new();
    /// <summary>room id → its name (an entry is keyed by both, like the browser's maps).</summary>
    public Dictionary<string, string> RoomNames { get; } = new();
    /// <summary><c>tile.roomLevels</c> (rooms + corridors, keyed by id and name).</summary>
    public Dictionary<string, int> RoomLevels { get; } = new();
    /// <summary><c>tile.alwaysVisibleRooms</c> (outdoor + always-visible rooms, id and name).</summary>
    public HashSet<string> AlwaysVisible { get; } = new();

    /// <summary>Derived: <c>tile.roomCenters</c> (room stands under id and name; corridor stands under the corridor id).</summary>
    public Dictionary<string, Vec3> RoomCenters { get; } = new();
    public Dictionary<string, IReadOnlyList<Vec3>> SitSpots { get; } = new();
    public Dictionary<string, IReadOnlyList<Vec3>> LieSpots { get; } = new();
    public Dictionary<string, RoomRect> RoomRects { get; } = new();

    private RoomFloor? FloorOf(string roomId)
    {
        foreach (var kv in RoomFloors) if (kv.Key == roomId) return kv.Value;
        return null;
    }

    private double World(double x, double z) => WorldGround?.Invoke(x, z) ?? double.NaN;

    /// <summary><c>bakedFloorAt</c>: the highest answering lattice among <paramref name="keep"/> (world y), else null.</summary>
    public double? BakedFloorAt(double lx, double lz, Func<PlacedSurface, bool> keep)
    {
        if (Surfaces.Count == 0) return null;
        return SurfaceHeight.Highest(Surfaces.Where(keep), lx, lz) is { } baked ? Frame.Center.Y + baked : null;
    }

    /// <summary>
    /// <c>tileWalkY</c>: one turn into the tile frame; the storey-0 lattices, else a declaration, else a plate under the
    /// storey ceiling — each asked only while the rungs above are silent — through <see cref="FigureGround.TileWalkLadder"/>.
    /// </summary>
    public double TileWalkY(double x, double z)
    {
        var local = SceneView.WorldToTile(Frame, x, z);
        var baked = BakedFloorAt(local.X, local.Z, e => e.Level == 0);
        double? declared = baked is null && DeclaredFloors.Count > 0 ? FigureGround.DeclaredFloorAt(DeclaredFloors, local.X, local.Z) : null;
        double? plate = null;
        if (baked is null && declared is null && WalkPlates.Count > 0)
            plate = FigureGround.RecipeFloorAt(WalkPlates, local.X, local.Z, FigureGround.PlateCeiling(ModelWalkY));
        return FigureGround.TileWalkLadder(Frame.Center.Y, baked, declared, plate);
    }

    /// <summary><c>tileGroundY</c>: <see cref="FigureGround.StandY"/> of the tile's answer and the world's (NaN = none).</summary>
    public double TileGroundY(double x, double z) => FigureGround.StandY(TileWalkY(x, z), World(x, z));

    /// <summary><c>roomFloorWorldY</c>: this room's own lattices (any storey), else <see cref="RoomBaseFloorY"/>.</summary>
    public double RoomFloorWorldY(string roomId, RoomFloor floor, double lx, double lz)
    {
        var baked = BakedFloorAt(lx, lz, e => e.RoomId == roomId);
        if (baked is not null) return FigureGround.RoomFloorLadder(Frame.Center.Y, baked, floor.Declared, double.NaN);
        return RoomBaseFloorY(floor, lx, lz);
    }

    /// <summary><c>roomBaseFloorY</c>: the declaration, else the terrain at the point (sampled only then).</summary>
    public double RoomBaseFloorY(RoomFloor floor, double lx, double lz)
    {
        double terrain = double.NaN;
        if (floor.Declared is null)
        {
            var w = SceneView.TileToWorld(Frame, lx, lz);
            terrain = World(w.X, w.Z);
        }
        return FigureGround.RoomFloorLadder(Frame.Center.Y, null, floor.Declared, terrain);
    }

    /// <summary><c>roomFloorAt</c>: the room's floor at a tile-local point, null when the tile has no floor for it.</summary>
    public double? RoomFloorAt(string roomId, double lx, double lz)
        => FloorOf(roomId) is { } floor ? RoomFloorWorldY(roomId, floor, lx, lz) : null;

    /// <summary><c>roomStandY</c>: <see cref="FigureGround.RoomStandLadder"/> of the room's floor and its stand centre.</summary>
    public double? RoomStandY(string roomId, double lx, double lz)
        => FigureGround.RoomStandLadder(RoomFloorAt(roomId, lx, lz), RoomCenters.TryGetValue(roomId, out var c) ? c.Y : null);

    /// <summary>
    /// <c>deriveRoomSpots(tile, roomId, props)</c>: no floor or no rectangle = nothing; else <see cref="RoomSpots.Of"/>
    /// over the room's markers (<paramref name="places"/>, keyed by room id) writes the rectangle, the centre (id and
    /// name), the sit / lie lists (only when non-empty — an empty list leaves an older one, as the browser's
    /// <c>put</c> does) and every non-fixed marker's slot heights, absolutely, in place.
    /// </summary>
    public void DeriveRoom(string roomId, IReadOnlyList<SpotBox> props, PlaceInventory? places)
    {
        if (FloorOf(roomId) is not { } floor) return;
        if (Ambience.RoomRectOf(floor.Hull) is null) return;
        var entries = places is not null && places.Markers.TryGetValue(roomId, out var byId) ? byId.Values.ToList() : new List<PlaceEntry>();
        var spots = RoomSpots.Of(floor.Hull, Frame, (lx, lz) => RoomFloorWorldY(roomId, floor, lx, lz),
                                 (lx, lz) => RoomBaseFloorY(floor, lx, lz), props,
                                 entries.Select(e => new SpotMarker(e.Slots, e.Drop, e.OffsetY, e.Fixed)).ToList());
        if (spots is null) return;
        RoomRects[roomId] = spots.Rect;
        RoomCenters[roomId] = spots.Centre;
        RoomNames.TryGetValue(roomId, out var name);
        if (!string.IsNullOrEmpty(name)) RoomCenters[name] = spots.Centre;
        void Put(Dictionary<string, IReadOnlyList<Vec3>> map, IReadOnlyList<Vec3> list)
        {
            if (list.Count == 0) return;
            map[roomId] = list;
            if (!string.IsNullOrEmpty(name)) map[name] = list;
        }
        Put(SitSpots, spots.Sit);
        Put(LieSpots, spots.Lie);
        for (int i = 0; i < entries.Count; i++)
        {
            if (spots.MarkerY[i] is not { } y) continue;
            var slots = entries[i].Slots;
            for (int k = 0; k < slots.Length; k++) slots[k] = slots[k] with { Y = y };
        }
    }

    /// <summary>
    /// The browser's pass after a mount / re-lift: every room floor re-derived (<see cref="DeriveRoom"/>, its props from
    /// <paramref name="propsOf"/>), then the corridor stands (<c>deriveCorridorCentres</c>: a declared storey on its plate,
    /// storey 0 on <see cref="TileGroundY"/>) into <see cref="RoomCenters"/>.
    /// </summary>
    public void DeriveAll(Func<string, IReadOnlyList<SpotBox>> propsOf, PlaceInventory? places)
    {
        foreach (var (id, _) in RoomFloors.ToList()) DeriveRoom(id, propsOf(id), places);
        if (places is null) return;
        places.DeriveCorridorStands(Frame, TileGroundY);
        foreach (var c in places.Corridors)
            if (c.Stand is { } s) RoomCenters[c.RoomId] = s;
    }

    /// <summary>A storey's corridors as the placement reads them (room ids).</summary>
    public static IReadOnlyList<string> CorridorIds(PlaceInventory? places)
        => places?.Corridors.Select(c => c.RoomId).ToList() ?? new List<string>();
}
