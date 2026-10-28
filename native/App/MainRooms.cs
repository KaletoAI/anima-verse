using System.Collections.Generic;
using System.Text.Json.Nodes;
using AnimaNative.Scene;

namespace AnimaNative;

/// <summary>Task 51 / E7-T6: Main owns the controller; HUD v3 owns locks and corridor IDs, never the scene offers.</summary>
public partial class Main
{
    private void TickAvatarRooms()
    {
        if (_avatarRooms is not { } rooms || _hud is not { } hud) return;
        rooms.SetActive(Embodied && !Leaving);
        var locks = LockState.FromHud(hud.HudOwned("lockedRooms"), hud.HudOwned("lockedLoc"), null, "");
        rooms.LockedRooms = locks.Rooms; rooms.LockedLoc = locks.Loc;
        rooms.GroundRoomId = hud.HudOwned("groundRoomId")?.GetValue<string>() ?? "";
        var floors = new Dictionary<int,string>();
        if (hud.HudOwned("floorRoomIds") is JsonObject ids)
            foreach (var (key, value) in ids)
                if (int.TryParse(key, out int level) && value is JsonValue v && v.TryGetValue<string>(out var id)) floors[level] = id;
        rooms.FloorRoomIds = floors;
        rooms.Tick();
        // The probe also follows a stationary pointer when camera easing or offer eligibility changes.
        if (_camera is { } camera && _hoverAt is { } at && !hud.PointerOverHud && hud.Active)
        {
            var (o, d) = camera.RayAt(at);
            rooms.Picking.Hover(rooms.Picking.Hit(o, d));
            Hover(at);
        }
        else rooms.Picking.Clear();
    }
}
