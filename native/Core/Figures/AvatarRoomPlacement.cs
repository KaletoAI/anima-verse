using System;
using AnimaNative.Overview;
using AnimaNative.Scatter;
using AnimaNative.Scene;

namespace AnimaNative.Figures;

public sealed record AvatarRoomCorrection(string OldRoom, int OldLevel, string Room, int Level, Vec3 Point)
{
    public string Transition => $"room={OldRoom} storey={OldLevel} -> room={Room} storey={Level}";
}

/// <summary>Infer the body's storey from rendered Y and authored floors, never the just-adopted row room.
/// Origin is deliberately absent: a server room-only write can retain our last position origin.</summary>
public static class AvatarRoomPlacement
{
    public static bool Inside(PlacementTile tile, string room, P2 point)
    {
        var p=SceneView.WorldToTile(tile.Frame,point.X,point.Z);
        return double.IsFinite(point.X) && double.IsFinite(point.Z)
            && tile.RoomFloors.TryGetValue(room,out var floor) && SceneView.PolygonDistance(p.X,p.Z,floor.Hull)<=.3;
    }

    public static AvatarRoomCorrection? Correction(PlacementTile tile, Vec3 body, string room, P2 rowPoint,
        Func<string,double,double,double?> floorY, bool ownRide=false, string? bodyRoom=null)
    {
        if(ownRide || !tile.RoomCenters.TryGetValue(room,out var centre) || !tile.RoomLevels.TryGetValue(room,out int level)
            || !tile.RoomFloors.ContainsKey(room)) return null;
        var local=SceneView.WorldToTile(tile.Frame,body.X,body.Z);
        string? oldRoom=null; int oldLevel=0; double best=double.PositiveInfinity;
        // Height chooses the floor; containment only breaks ties between adjacent rooms on that floor.
        bool bestInside=false, inLocation=false;
        foreach(var (id,c) in tile.RoomCenters)
        {
            if(!tile.RoomLevels.TryGetValue(id,out int candidateLevel)) continue;
            double distance=Math.Abs(body.Y-(floorY(id,local.X,local.Z) ?? c.Y));
            bool inside=Inside(tile,id,new(body.X,body.Z));
            inLocation |= inside;
            if(distance<best-1e-6 || Math.Abs(distance-best)<=1e-6 && inside && !bestInside)
            { oldRoom=id; oldLevel=candidateLevel; best=distance; bestInside=inside; }
        }
        // A distant point with a stale room belongs to the ordinary teleport/readiness path.
        if(!inLocation || oldRoom is null || oldLevel==level && (bodyRoom==room || Inside(tile,room,new(body.X,body.Z)))) return null;
        var at=SceneView.WorldToTile(tile.Frame,rowPoint.X,rowPoint.Z);
        var point=Inside(tile,room,rowPoint) ? new Vec3(rowPoint.X,floorY(room,at.X,at.Z) ?? centre.Y,rowPoint.Z) : centre;
        return new(bodyRoom ?? oldRoom,oldLevel,room,level,point);
    }
}
