using System.IO;
using System.Linq;
using System.Text.Json;
using AnimaNative.Figures;
using AnimaNative.Overview;
using AnimaNative.Scatter;
using AnimaNative.Scene;
using AnimaNative.Tests.Vectors;
using Xunit;

namespace AnimaNative.Tests;

public class AvatarRoomTests
{
    // Literal expectations are derived by hand in avatar_rooms.json, shared with Godot and the browser.
    [Fact]
    public void BodyFloorOverridesEchoAndDistanceButNeverAnOwnRide()
    {
        using var doc = JsonDocument.Parse(File.ReadAllBytes(Path.Combine(VectorFile.Directory,
            "../../native/fixtures/placement/avatar_rooms.json")));
        var root = doc.RootElement;
        static Vec3 V(JsonElement p) => new(p.GetProperty("x").GetDouble(),p.GetProperty("y").GetDouble(),p.GetProperty("z").GetDouble());
        var rooms=root.GetProperty("rooms").EnumerateObject().ToArray();
        var tile=new PlacementTile {
            Frame=new(V(root.GetProperty("center")),root.GetProperty("yaw").GetDouble()),
            RoomCenters=rooms.ToDictionary(r=>r.Name,r=>V(r.Value.GetProperty("center"))),
            RoomLevels=rooms.ToDictionary(r=>r.Name,r=>r.Value.GetProperty("level").GetInt32()),
            RoomFloors=rooms.ToDictionary(r=>r.Name,r=>new RoomFloor { Hull=r.Value.GetProperty("hull").EnumerateArray().Select(p=>new P2(p[0].GetDouble(),p[1].GetDouble())).ToArray() }),
        };
        var body=new Vec3(tile.Frame.Center.X,.01,tile.Frame.Center.Z);
        foreach(var c in root.GetProperty("cases").EnumerateArray())
        {
            var correction=AvatarRoomPlacement.Correction(tile,body,c.GetProperty("room").GetString()!,
                c.TryGetProperty("pos",out var p) ? new(p.GetProperty("x").GetDouble(),p.GetProperty("z").GetDouble()) : new(body.X,body.Z),
                (room,_,_)=>tile.RoomCenters[room].Y,c.GetProperty("ride").GetBoolean(),
                c.TryGetProperty("bodyRoom",out var ownRoom) ? ownRoom.GetString() : "lower");
            Assert.Equal(c.GetProperty("correct").GetBoolean(),correction is not null);
            if(correction is {} move) {
                Assert.Equal(V(c.GetProperty("expected")),move.Point);
                Assert.Equal(0,move.OldLevel);
            }
        }
    }
}
