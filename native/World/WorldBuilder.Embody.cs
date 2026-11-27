using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using AnimaNative.Embody;
using AnimaNative.Figures;
using AnimaNative.Overview;
using AnimaNative.Scatter;
using AnimaNative.Scene;
using Godot;

namespace AnimaNative.World;

/// <summary>Task 49 / E7-T4: main.ts walking lookups over the same mounted ground ladder used by NPCs.</summary>
public sealed partial class WorldBuilder
{
    public bool PhotoMode { get; set; }
    /// <summary>Reveal the authoritative room before the avatar's first placement, like browser placeAvatarOnArrival.</summary>
    public bool PrepareAvatarArrival(JsonElement map)
    {
        if (PhotoMode || AvatarSession.Suspended(map)) return true;
        string name = Json.Str(map, "avatar");
        foreach (var row in Json.Arr(map, "characters"))
        {
            if (Json.Str(row, "name") != name) continue;
            string id = Json.Str(row, "location_id"), room = Json.Str(row, "room_id");
            if (id.Length == 0 || (row.TryGetProperty("travel", out var travel) && travel.ValueKind == JsonValueKind.Object)) return true;
            // No slot at all (off-map / no scene): nothing to prepare, place as before. A mounting slot is waited for.
            if (!_slots.TryGetValue(id, out var slot)) return true;
            if (!slot.Ready) return false;
            SetLevel(id, slot.Stands.RoomLevels.GetValueOrDefault(room));
            if (slot.Openable)
            {
                SetOpen(id, true);
                slot.Fade.Snap(1);
            }
            slot.Storeys.Apply(slot.LevelFilter, slot.Openable ? slot.Fade.Fade : 0, slot.Openable, slot.Fade);
            _log($"[spawn] view location={id} room={room} storey={slot.LevelFilter} interior={slot.Fade.Fade} ready={slot.Ready}");
            return true;
        }
        return true;
    }

    private readonly Dictionary<(string Id, int Level), (LocationSlot Slot, ScenePayload Scene, TileFrame Frame, List<WallSegment> Full, List<WallSegment> Inner)> _avatarWalls = new();
    private readonly Dictionary<string, (LocationInfo Loc, P2[] Ring, PolygonExtent Bounds)> _boundaryRings = new(StringComparer.Ordinal);

    public LocationSlot? FootprintAt(double x, double z) => TileAt(x,z)?.Slot;

    /// <summary>Browser photoFloorY: shown-storey surface below the camera, room/corridor centre, terrain.</summary>
    public double PhotoFloorY(Vector3 camera)
    {
        double x=camera.X, z=camera.Z, terrain=FigureGroundY(x,z);
        if (FootprintAt(x,z) is not { Open:true } tile) return terrain;
        var local=SceneView.WorldToTile(tile.Stands.Frame,x,z);
        var floor=tile.Stands.BakedFloorAt(local.X,local.Z,s=>
            tile.Stands.RoomLevels.TryGetValue(s.RoomId,out int level) && level==tile.LevelFilter);
        if (floor is { } baked && baked<=camera.Y) return baked;
        string? room=Ambience.RoomAtRects(tile.RoomRects,local.X,local.Z)
            ?? Ambience.CorridorAtOutline(tile.Corridors,local.X,local.Z);
        return room is not null && tile.Stands.RoomCenters.TryGetValue(room,out var centre) && centre.Y<=camera.Y ? centre.Y : terrain;
    }

    /// <summary>
    /// Terrain, fenced-plot gate rules and uphill gates; refused-disc memory belongs to the caller.
    /// Rule (a): entering a foreign fenced place away from its gates is blocked (both steps and click targets).
    /// Rule (b): leaving the avatar's own fenced place away from its gates is blocked for steps (when <paramref name="from"/>
    /// lies on <paramref name="mine"/>), never for target checks (<paramref name="from"/> is null).
    /// </summary>
    public bool PlayerBlocked(LocationSlot? mine, double x, double z, P2? from, EntryWorld entry)
    {
        var there = TileAt(x,z);
        if (Walk.TerrainBlocks(Ground?.Catalog.PassableAt(x,z) ?? true, there is not null)) return true;
        var tol = entry.Tolerance;
        bool AtAnyGate(string id, double px, double pz)
        {
            foreach (var g in entry.Gates(id))
                if (EntryRules.AtGate(g.AtWorld, px, pz, tol)) return true;
            return false;
        }
        bool AtAnyDoor(string id, double px, double pz)
        {
            foreach (var d in entry.Doors(id))
                if (EntryRules.AtDoor(d, px, pz, tol)) return true;
            return false;
        }
        if (there is { } foreign && foreign.Slot != mine && entry.Fenced(foreign.Slot.Loc.Id)
            && !AtAnyGate(foreign.Slot.Loc.Id, x, z))
            return true;
        if (from is not { } f) return false;
        var here = TileAt(f.X,f.Z);
        if (mine is not null && here?.Slot == mine && entry.Fenced(mine.Loc.Id) && there?.Slot != mine
            && !AtAnyGate(mine.Loc.Id, x, z))
            return true;
        double Stand(double xx, double zz, (LocationSlot Slot, P2 Local)? tile)
        {
            double bed = GateBedAt(xx,zz,tile);
            return PropWaterAt(xx,zz,tile) is { } water ? Math.Max(bed,water.Y) : bed;
        }
        double dh = Stand(x,z,there) - Stand(f.X,f.Z,here);
        if (!Walk.SlopeBlocks(dh,double.Hypot(x-f.X,z-f.Z),entry.MaxStepM,entry.MaxSlopeDeg)) return false;
        bool NearOpening(LocationSlot? slot) => slot is not null
            && (AtAnyGate(slot.Loc.Id, x, z) || AtAnyGate(slot.Loc.Id, f.X, f.Z)
                || AtAnyDoor(slot.Loc.Id, x, z) || AtAnyDoor(slot.Loc.Id, f.X, f.Z));
        return !NearOpening(there?.Slot) && (here?.Slot == there?.Slot || !NearOpening(here?.Slot));
    }

    /// <summary>Task 49: room floor stays on the avatar's storey; outdoor rooms fall back to groundY.</summary>
    public double PlayerFloorY(LocationSlot? tile, string room, double x, double z)
    {
        if (tile?.IsBuilding == true && room.Length > 0 && !tile.Stands.AlwaysVisible.Contains(room))
        {
            var st = tile.Stands;
            var p = SceneView.WorldToTile(st.Frame,x,z);
            if (st.BakedFloorAt(p.X,p.Z,s => s.RoomId == room) is { } baked) return baked + FigureGround.WalkClearanceM;
            if (st.RoomCenters.TryGetValue(room,out var centre)) return centre.Y;
        }
        return FigureGroundY(x,z);
    }

    private (List<WallSegment> Full, List<WallSegment> Inner) LevelWalls(LocationSlot tile, ScenePayload scene, int level)
    {
        var key = (tile.Loc.Id, level);
        var frame = tile.Stands.Frame;
        if (!_avatarWalls.TryGetValue(key, out var cache) || cache.Slot != tile || cache.Scene != scene || cache.Frame != frame)
        {
            var localSegs = Collide.WallSegments(scene, level);
            var full = new List<WallSegment>(localSegs.Count);
            P2[]? ring = tile.Loc.Boundary is { Length: >= 3 } b ? BoundaryRing(tile, b).Ring : null;
            double hullTol = 0.3 * (double.IsFinite(scene.K) && scene.K > 0 ? scene.K : 1);
            bool OnHull(double lx, double lz) => SceneView.NearestRimPoint(lx, lz, ring) is { } r && r.Dist <= hullTol;
            var inner = ring is null ? full : new List<WallSegment>(localSegs.Count);
            foreach (var s in localSegs)
            {
                var a = SceneView.TileToWorld(frame, s.Ax, s.Az);
                var bPt = SceneView.TileToWorld(frame, s.Bx, s.Bz);
                var worldSeg = new WallSegment(a.X, a.Z, bPt.X, bPt.Z);
                full.Add(worldSeg);
                if (ring is not null && !(OnHull(s.Ax, s.Az) && OnHull(s.Bx, s.Bz) && OnHull((s.Ax + s.Bx) * 0.5, (s.Az + s.Bz) * 0.5)))
                    inner.Add(worldSeg);
            }
            cache = (tile, scene, frame, full, inner);
            _avatarWalls[key] = cache;
        }
        return (cache.Full, cache.Inner);
    }

    private (P2[] Ring, PolygonExtent Bounds) BoundaryRing(LocationSlot slot, (double X, double Z)[] boundary)
    {
        if (_boundaryRings.TryGetValue(slot.Loc.Id, out var cached) && ReferenceEquals(cached.Loc, slot.Loc))
            return (cached.Ring, cached.Bounds);
        var ring = new P2[boundary.Length];
        double minX = double.PositiveInfinity, minZ = double.PositiveInfinity;
        double maxX = double.NegativeInfinity, maxZ = double.NegativeInfinity;
        for (int i = 0; i < boundary.Length; i++)
        {
            double x = boundary[i].X, z = boundary[i].Z;
            ring[i] = new P2(x, z);
            if (x < minX) minX = x; if (x > maxX) maxX = x;
            if (z < minZ) minZ = z; if (z > maxZ) maxZ = z;
        }
        var bounds = new PolygonExtent(minX, minZ, maxX, maxZ);
        _boundaryRings[slot.Loc.Id] = (slot.Loc, ring, bounds);
        return (ring, bounds);
    }

    /// <summary>
    /// Cache per location/storey, invalidate on remount or frame changes. Transform both local endpoints after
    /// wallSegments applies doorway ease. For an unfenced building with no outside doors (no-trap rule), hull
    /// segments on the footprint boundary are dropped so the avatar is never trapped inside, while partition walls stay.
    /// Unknown avatar room/storey or closed interior supplies no invisible collision.
    /// </summary>
    public (IReadOnlyList<WallSegment> Segments, double Radius)? PlayerWalls(LocationSlot? tile, string room, EntryWorld entry)
    {
        if (tile?.IsBuilding != true || tile.Fade.Interior?.Visible != true || tile.Scene is not { } scene
            || !tile.Stands.RoomLevels.TryGetValue(room,out int level)) return null;
        var (full, inner) = LevelWalls(tile, scene, level);
        bool noTrap = !entry.Fenced(tile.Loc.Id) && entry.Doors(tile.Loc.Id).Count == 0;
        var segments = noTrap ? inner : full;
        return segments.Count == 0 ? null : (segments, Collide.BodyRadius(scene.K));
    }

    /// <summary>
    /// Level-0 building walls for every building slot whose footprint (x, z) touches within body radius + step lead.
    /// Independent of interior visibility and avatar room, except skipping the avatar's own slot when on another storey,
    /// and skipping unfenced buildings with no outside doors (no-trap rule; a location unknown to <paramref name="entry"/>
    /// counts as unfenced with no doors and is skipped).
    /// </summary>
    public (IReadOnlyList<WallSegment> Segments, double Radius)? OutsideWalls(
        LocationSlot? here, string room, double x, double z, EntryWorld entry, double lead = PlayerSteering.MinLead)
    {
        List<WallSegment>? single = null;
        List<WallSegment>? combined = null;
        double maxRadius = 0;
        double stepLead = Math.Max(0, lead);
        foreach (var slot in _slots.Values)
        {
            if (!slot.IsBuilding || slot.Scene is not { } scene || !GodotObject.IsInstanceValid(slot.Group)
                || slot.Loc.Boundary is not { Length: >= 3 } boundary) continue;
            if (!entry.Fenced(slot.Loc.Id) && entry.Doors(slot.Loc.Id).Count == 0) continue;
            if (slot == here && room.Length > 0 && slot.Stands.RoomLevels.TryGetValue(room, out int roomLevel) && roomLevel != 0)
                continue;
            double radius = Collide.BodyRadius(scene.K);
            double reach = radius + stepLead;
            var local = SceneView.WorldToTile(slot.Stands.Frame, x, z);
            var (ring, bounds) = BoundaryRing(slot, boundary);
            if (local.X < bounds.MinX - reach || local.X > bounds.MaxX + reach
                || local.Z < bounds.MinZ - reach || local.Z > bounds.MaxZ + reach)
                continue;
            if (SceneView.PolygonDistance(local.X, local.Z, ring) > reach)
                continue;
            var segs = LevelWalls(slot, scene, 0).Full;
            if (segs.Count == 0) continue;
            if (single is null && combined is null)
            {
                single = segs;
                maxRadius = radius;
            }
            else
            {
                if (combined is null) { combined = new List<WallSegment>(single!.Count + segs.Count); combined.AddRange(single); single = null; }
                combined.AddRange(segs);
                maxRadius = Math.Max(maxRadius, radius);
            }
        }
        var result = combined ?? single;
        return result is null ? null : (result, maxRadius);
    }

    private readonly ReadinessState _playerReadiness = new();
    /// <summary>Task 50: use the vectored readiness owner lifecycle over the residency pin map.</summary>
    public bool HoldPlayerApproach(double x, double z) => Readiness.HoldFor(this, _playerReadiness, x, z);
    public void ClearPlayerApproach() => Readiness.ClearApproach(this, _playerReadiness);
}
