using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using System.Text.Json.Nodes;
using AnimaNative.World;

namespace AnimaNative.Overview;

/// <summary>A room of a location row: <c>id</c> and <c>name</c> as the payload has them (null when absent).</summary>
public sealed record InfoRoom(string? Id, string? Name);

/// <summary>
/// The parts of a world-map location row (TS <c>WorldLocation</c>) the info panel reads. Strings
/// are null when the row has no string there, so the panel can mirror the TS's
/// <c>undefined</c> comparisons exactly.
/// </summary>
public sealed record InfoLocation(
    string? Id, string? Name, string? Description, string? Terrain, bool AreaModel,
    double? PosX, double? PosZ, IReadOnlyList<InfoRoom> Rooms)
{
    /// <summary>Parse a location row of <c>GET /play/worldmap</c>.</summary>
    public static InfoLocation FromJson(JsonElement l)
    {
        var rooms = Json.Arr(l, "rooms")
            .Where(r => r.ValueKind == JsonValueKind.Object)
            .Select(r => new InfoRoom(StrOrNull(r, "id"), StrOrNull(r, "name")))
            .ToList();
        // `!!loc.map3d?.area_model`: the same truthiness rule as LocationInfo.Parse.
        bool area = l.ValueKind == JsonValueKind.Object && l.TryGetProperty("map3d", out var m3) && m3.ValueKind == JsonValueKind.Object
                    && m3.TryGetProperty("area_model", out var am) && Truthy(am);
        return new InfoLocation(StrOrNull(l, "id"), StrOrNull(l, "name"), StrOrNull(l, "description"),
                                StrOrNull(l, "terrain"), area, Json.NumOrNull(l, "pos_x"), Json.NumOrNull(l, "pos_z"), rooms);
    }

    internal static string? StrOrNull(JsonElement e, string name)
        => e.ValueKind == JsonValueKind.Object && e.TryGetProperty(name, out var v) && v.ValueKind == JsonValueKind.String
            ? v.GetString() : null;

    /// <summary>JS truthiness of a JSON value.</summary>
    private static bool Truthy(JsonElement v) => v.ValueKind switch
    {
        JsonValueKind.Null or JsonValueKind.False or JsonValueKind.Undefined => false,
        JsonValueKind.String => v.GetString() != "",
        JsonValueKind.Number => v.GetDouble() != 0,
        _ => true,
    };
}

/// <summary>The parts of a world-map character row (TS <c>MapCharacter</c>) the info panel reads.</summary>
public sealed record InfoCharacter(string? Name, string? Activity, string? Mood, string? MovementTargetName, string? EtaHhmm)
{
    /// <summary>Parse a character row of <c>GET /play/worldmap</c> (<c>travel.eta_hhmm</c> from the journey).</summary>
    public static InfoCharacter FromJson(JsonElement c)
    {
        string? eta = c.ValueKind == JsonValueKind.Object && c.TryGetProperty("travel", out var tr) ? InfoLocation.StrOrNull(tr, "eta_hhmm") : null;
        return new InfoCharacter(InfoLocation.StrOrNull(c, "name"), InfoLocation.StrOrNull(c, "activity"),
                                 InfoLocation.StrOrNull(c, "mood"), InfoLocation.StrOrNull(c, "movement_target_name"), eta);
    }
}

/// <summary>An event row (TS <c>MapEvent</c>): <c>category</c> and <c>text</c>.</summary>
public sealed record InfoEvent(string? Category, string? Text)
{
    public static InfoEvent FromJson(JsonElement e)
        => new(InfoLocation.StrOrNull(e, "category"), InfoLocation.StrOrNull(e, "text"));
}

/// <summary>Whether the location's interior can be opened and is open (the scene's own state).</summary>
public readonly record struct InfoView(bool Openable, bool Open);

/// <summary>Where the player's avatar is: its location and its ground position (null when unknown).</summary>
public sealed record InfoAvatar(string LocationId, (double X, double Z)? Pos);

/// <summary>
/// Port of client3d/src/game/infoPanel.ts — the location info panel's data, computed by the
/// scene and rendered by the HUD. <see cref="Build"/> returns a <see cref="JsonObject"/> in exactly
/// the HUD's <c>InfoPanelData</c> shape (camelCase keys, in the TS order), so it goes over the
/// bridge unchanged. Vectors: shared/test-vectors/overview_hud.json [I1..I12].
/// </summary>
public static class InfoPanel
{
    /// <summary>Terrains whose rooms are generic zones: the panel lists no rooms for them.</summary>
    private static readonly string[] AreaTerrains = { "water", "forest", "grass", "road", "sand", "rock" };

    /// <summary>
    /// <c>infoPanelData(loc, chars, events, roomOf, view?, avatar?)</c>. <paramref name="roomOf"/>
    /// maps a character name to the room name OR id it is in; a room matches both, exactly as the
    /// TS compares (a room without a name therefore matches every character without a room, as
    /// <c>undefined === undefined</c> does there). Travel is offered when the avatar is in another
    /// location, with a distance only when both positions are known.
    /// </summary>
    public static JsonObject Build(InfoLocation loc, IReadOnlyList<InfoCharacter> chars, IReadOnlyList<InfoEvent> events,
                                   IReadOnlyDictionary<string, string> roomOf, InfoView? view, InfoAvatar? avatar)
    {
        bool area = loc.AreaModel || AreaTerrains.Contains((loc.Terrain ?? "").ToLowerInvariant());
        string? RoomOf(InfoCharacter c) => c.Name is string n && roomOf.TryGetValue(n, out var r) ? r : null;

        var rooms = new JsonArray();
        if (!area)
        {
            foreach (var r in loc.Rooms)
            {
                var who = new JsonArray();
                foreach (var c in chars)
                {
                    string? where = RoomOf(c);
                    if (where == r.Name || where == r.Id) who.Add(c.Name ?? "");
                }
                rooms.Add(new JsonObject { ["name"] = r.Name ?? "", ["who"] = who });
            }
        }

        var present = new JsonArray();
        foreach (var c in chars)
            present.Add(new JsonObject
            {
                ["name"] = c.Name ?? "",
                ["activity"] = c.Activity ?? "",
                ["mood"] = c.Mood ?? "",
                ["travelTo"] = c.MovementTargetName ?? "",
                ["eta"] = c.EtaHhmm ?? "",
            });

        var evs = new JsonArray();
        foreach (var e in events)
            evs.Add(new JsonObject { ["danger"] = e.Category == "danger", ["text"] = e.Text ?? "" });

        JsonObject? travel = null;
        if (avatar is not null && avatar.LocationId != loc.Id)
        {
            double? distance = avatar.Pos is (double ax, double az) && loc.PosX is double lx && loc.PosZ is double lz
                ? double.Hypot(lx - ax, lz - az) : null;
            travel = new JsonObject { ["distanceM"] = distance };
        }

        var data = new JsonObject();
        // `id: loc.id` — an absent id is undefined in the TS and JSON.stringify drops the key.
        if (loc.Id is not null) data["id"] = loc.Id;
        data["name"] = loc.Name ?? "";
        data["description"] = loc.Description ?? "";
        data["rooms"] = rooms;
        data["present"] = present;
        data["events"] = evs;
        data["travel"] = travel;
        data["view"] = view is InfoView v ? new JsonObject { ["openable"] = v.Openable, ["open"] = v.Open } : null;
        return data;
    }

    /// <summary>
    /// main.ts <c>engine.onPick(id)</c>, the inputs gathered from one <c>GET /play/worldmap</c> payload: the
    /// location row of <paramref name="id"/> (null when the map has none — the panel then stays as it is),
    /// the characters whose <c>location_id</c> is it, its <c>events_by_location</c> entry, every character's
    /// room (<c>takeRoomsFrom</c>: <c>room_id ?? ''</c>) and the avatar (<c>map.avatar</c>'s row: its
    /// <c>location_id</c> and <c>pos ?? null</c>; no row → no avatar). <paramref name="view"/> is the scene's.
    /// </summary>
    public static JsonObject? FromWorldMap(JsonElement map, string id, InfoView view)
    {
        if (map.ValueKind != JsonValueKind.Object) return null;
        JsonElement? row = null;
        foreach (var l in Json.Arr(map, "locations"))
            if (InfoLocation.StrOrNull(l, "id") == id) { row = l; break; }
        if (row is not { } r) return null;
        var all = Json.Arr(map, "characters").Where(c => c.ValueKind == JsonValueKind.Object).ToList();
        var chars = all.Where(c => InfoLocation.StrOrNull(c, "location_id") == id).Select(InfoCharacter.FromJson).ToList();
        var events = new List<InfoEvent>();
        if (map.TryGetProperty("events_by_location", out var ebl) && ebl.ValueKind == JsonValueKind.Object
            && ebl.TryGetProperty(id, out var evs) && evs.ValueKind == JsonValueKind.Array)
            events.AddRange(evs.EnumerateArray().Select(InfoEvent.FromJson));
        var roomOf = new Dictionary<string, string>();
        foreach (var c in all)
            if (InfoLocation.StrOrNull(c, "name") is { } n) roomOf[n] = InfoLocation.StrOrNull(c, "room_id") ?? "";
        InfoAvatar? avatar = null;
        if (InfoLocation.StrOrNull(map, "avatar") is { } me)
            foreach (var c in all)
            {
                if (InfoLocation.StrOrNull(c, "name") != me) continue;
                (double, double)? pos = c.TryGetProperty("pos", out var p) && p.ValueKind == JsonValueKind.Object
                                        && Json.NumOrNull(p, "x") is double px && Json.NumOrNull(p, "z") is double pz
                    ? (px, pz) : null;
                avatar = new InfoAvatar(InfoLocation.StrOrNull(c, "location_id") ?? "", pos);
                break;
            }
        return Build(InfoLocation.FromJson(r), chars, events, roomOf, view, avatar);
    }
}
