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
        if (PhotoMode) return true;
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

    private readonly Dictionary<(string Id, int Level), (LocationSlot Slot, ScenePayload Scene, TileFrame Frame, List<WallSegment> Segments)> _avatarWalls = new();

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

    /// <summary>Task 49: worldmap openings remain authoritative even when a scene has no authored walls.</summary>
    private static IEnumerable<P2> OpeningsAt(JsonElement? map, string id)
    {
        if (map is not { } root) yield break;
        foreach (var l in Json.Arr(root,"locations"))
        {
            if (Json.Str(l,"id") != id) continue;
            foreach (var o in Json.Arr(l,"openings"))
                if (o.TryGetProperty("at_world", out var a) && a.ValueKind == JsonValueKind.Array && a.GetArrayLength() >= 2)
                    yield return new(a[0].GetDouble(), a[1].GetDouble());
        }
    }

    /// <summary>Task 49: terrain, foreign footprint and uphill gates; refused-disc memory belongs to the caller.</summary>
    public bool PlayerBlocked(LocationSlot? mine, double x, double z, P2? from, JsonElement? map)
    {
        var there = TileAt(x,z);
        if (Walk.TerrainBlocks(Ground?.Catalog.PassableAt(x,z) ?? true, there is not null)) return true;
        if (there is { } foreign && foreign.Slot != mine && OpeningsAt(map,foreign.Slot.Loc.Id).Any()) return true;
        if (from is not { } f) return false;
        var here = TileAt(f.X,f.Z);
        double Stand(double xx, double zz, (LocationSlot Slot, P2 Local)? tile)
        {
            double bed = GateBedAt(xx,zz,tile);
            return PropWaterAt(xx,zz,tile) is { } water ? Math.Max(bed,water.Y) : bed;
        }
        double dh = Stand(x,z,there) - Stand(f.X,f.Z,here);
        double maxStep = map is { } m ? Json.NumOrNull(m,"max_step_height_m") ?? .4 : .4;
        double maxSlope = map is { } n ? Json.NumOrNull(n,"max_slope_deg") ?? 40 : 40;
        if (!Walk.SlopeBlocks(dh,double.Hypot(x-f.X,z-f.Z),maxStep,maxSlope)) return false;
        bool NearOpening(LocationSlot? slot) => slot is not null && OpeningsAt(map,slot.Loc.Id).Any(o =>
            double.Hypot(o.X-x,o.Z-z) <= 1.5 || double.Hypot(o.X-f.X,o.Z-f.Z) <= 1.5);
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

    /// <summary>
    /// Task 49: cache per location/storey, invalidate on remount or frame changes. Transform BOTH local endpoints
    /// after wallSegments applies doorway ease; a rotated tile cannot be represented by adding its origin.
    /// Unknown avatar room/storey or closed interior supplies no invisible collision.
    /// </summary>
    public (IReadOnlyList<WallSegment> Segments, double Radius)? PlayerWalls(LocationSlot? tile, string room)
    {
        if (tile?.IsBuilding != true || tile.Fade.Interior?.Visible != true || tile.Scene is not { } scene
            || !tile.Stands.RoomLevels.TryGetValue(room,out int level)) return null;
        var key = (tile.Loc.Id,level);
        var frame = tile.Stands.Frame;
        if (!_avatarWalls.TryGetValue(key,out var cache) || cache.Slot != tile || cache.Scene != scene || cache.Frame != frame)
        {
            var segments = Collide.WallSegments(scene,level).Select(s =>
            {
                var a = SceneView.TileToWorld(frame,s.Ax,s.Az);
                var b = SceneView.TileToWorld(frame,s.Bx,s.Bz);
                return new WallSegment(a.X,a.Z,b.X,b.Z);
            }).ToList();
            cache = (tile,scene,frame,segments); _avatarWalls[key] = cache;
        }
        return cache.Segments.Count == 0 ? null : (cache.Segments,Collide.BodyRadius(scene.K));
    }

    private readonly ReadinessState _playerReadiness = new();
    /// <summary>Task 50: use the vectored readiness owner lifecycle over the residency pin map.</summary>
    public bool HoldPlayerApproach(double x, double z) => Readiness.HoldFor(this, _playerReadiness, x, z);
    public void ClearPlayerApproach() => Readiness.ClearApproach(this, _playerReadiness);
}
