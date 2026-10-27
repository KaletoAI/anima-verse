using System;
using System.Collections.Generic;
using System.Linq;
using System.Text.Json;
using AnimaNative.Overview;
using AnimaNative.Scatter;
using AnimaNative.World;

namespace AnimaNative.Figures;

/// <summary>
/// One character row of <c>GET /play/worldmap</c> (§ A1.4), reduced to what
/// the spike draws: where it stands, how tall it is, which mesh it wears.
/// </summary>
public sealed record CharacterRow(
    string Name, string LocationId, double? PosX, double? PosZ, double? HeightCm, string? ModelSig,
    TravelInfo? Travel)
{
    public bool HasPos => PosX.HasValue && PosZ.HasValue;

    /// <summary><c>activity_animation</c>: THE clip kind of a standing figure (npcs.ts → <c>standingClipFor</c>); "" = none.</summary>
    public string ActivityAnimation { get; init; } = "";

    /// <summary><c>animation_sets</c>: the character's set chain (<c>setCharacterSets</c>), the neutral set implied last.</summary>
    public IReadOnlyList<string> AnimationSets { get; init; } = Array.Empty<string>();

    /// <summary><c>model_rev</c>: the model's content revision (null = field absent); a change reloads like <c>model_sig</c>.</summary>
    public string? ModelRev { get; init; }

    /// <summary><c>room_id</c>: the room the character is in; "" = the location's ground (AV3D-8).</summary>
    public string RoomId { get; init; } = "";

    /// <summary><c>place</c>: the place the server seated the character on (id + slot), null = none.</summary>
    public PlaceRef? Place { get; init; }

    /// <summary><c>movement_target_id</c>: where the character means to go ("" = nowhere) — a standing figure faces it.</summary>
    public string MovementTargetId { get; init; } = "";

    /// <summary><c>avatar_url</c>: the portrait image a figure without a model shows ("" = none).</summary>
    public string AvatarUrl { get; init; } = "";

    /// <summary>
    /// <c>tagTravelling(travel)</c>: a travel block whose start does not lie ahead — the figure is under way (npcs.ts
    /// <c>npc.travelling</c>: it walks without the run boost).
    /// </summary>
    public bool Travelling { get; init; }

    /// <summary><c>interaction</c>: the running pair interaction (§ A8a); null = none (or a block without an anchor).</summary>
    public PairInteraction? Interaction { get; init; }

    /// <summary>
    /// <c>motion</c> (§ A11a: the resolved secondary-motion payload, <c>{rev, groups}</c>) and whether the row carries
    /// the field at all — <c>refreshIfChanged(…, c.motion)</c> keeps the known payload when it is absent.
    /// </summary>
    public MotionPayload? Motion { get; init; }
    public bool HasMotion { get; init; }

    public static List<CharacterRow> ParseList(JsonElement root)
        => Json.Arr(root, "characters")
               .Where(c => c.ValueKind == JsonValueKind.Object)
               .Select(Parse)
               .Where(c => c.Name.Length > 0)
               .ToList();

    private static CharacterRow Parse(JsonElement c)
    {
        double? px = null, pz = null;
        if (c.TryGetProperty("pos", out var pos) && pos.ValueKind == JsonValueKind.Object)
        {
            px = Json.NumOrNull(pos, "x");
            pz = Json.NumOrNull(pos, "z");
        }
        TravelInfo? travel = null;
        if (c.TryGetProperty("travel", out var tr) && tr.ValueKind == JsonValueKind.Object)
        {
            List<(double X, double Z)>? wp = null;
            if (tr.TryGetProperty("waypoints", out var w) && w.ValueKind == JsonValueKind.Array)
                wp = Json.Ring(w).ToList();
            travel = new TravelInfo(wp, Json.NumOrNull(tr, "progress_m"));
        }
        string? sig = c.TryGetProperty("model_sig", out var s) && s.ValueKind == JsonValueKind.String ? s.GetString() : null;
        var sets = c.TryGetProperty("animation_sets", out var a) && a.ValueKind == JsonValueKind.Array
            ? a.EnumerateArray().Where(e => e.ValueKind == JsonValueKind.String).Select(e => e.GetString()!).ToList()
            : new List<string>();
        string? rev = c.TryGetProperty("model_rev", out var r) && r.ValueKind == JsonValueKind.String ? r.GetString() : null;
        PlaceRef? place = null;
        if (c.TryGetProperty("place", out var pl) && pl.ValueKind == JsonValueKind.Object && Json.Str(pl, "id") is { Length: > 0 } pid)
        {
            // slot: a number, or 'pair' (the mean of the slots, PlaceSlots.SlotFor(null)); anything else reads as slot 0.
            int? slot = pl.TryGetProperty("slot", out var sl) && sl.ValueKind == JsonValueKind.String && sl.GetString() == "pair" ? null
                : sl.ValueKind == JsonValueKind.Number ? (int)sl.GetDouble() : 0;
            place = new PlaceRef(pid, slot);
        }
        return new CharacterRow(Json.Str(c, "name"), Json.Str(c, "location_id"), px, pz,
                                Json.NumOrNull(c, "height_cm"), sig, travel)
        {
            ActivityAnimation = Json.Str(c, "activity_animation"),
            AnimationSets = sets,
            ModelRev = rev,
            RoomId = Json.Str(c, "room_id"),
            Place = place,
            MovementTargetId = Json.Str(c, "movement_target_id"),
            AvatarUrl = Json.Str(c, "avatar_url"),
            Travelling = OverviewLabels.TagTravelling(TagTravel.FromJson(c)),
            Interaction = ParseInteraction(c),
            HasMotion = c.TryGetProperty("motion", out var mo),
            Motion = c.TryGetProperty("motion", out mo) ? MotionPayload.Parse(mo) : null,
        };
    }

    /// <summary>
    /// § A8a <c>interaction</c> as npcs.ts <c>adoptInteraction</c> reads it: no block or no <c>anchor</c> = none;
    /// <c>rate ?? 0</c>, <c>clip_duration_s ?? 0</c>, <c>!!loop</c>, <c>anchor.place_id ?? null</c>; a missing
    /// <c>elapsed_s</c> is NaN (the browser's <c>undefined</c>: no server clock to adopt).
    /// </summary>
    private static PairInteraction? ParseInteraction(JsonElement c)
    {
        if (!c.TryGetProperty("interaction", out var it) || it.ValueKind != JsonValueKind.Object) return null;
        if (!it.TryGetProperty("anchor", out var a) || a.ValueKind != JsonValueKind.Object) return null;
        string? place = a.TryGetProperty("place_id", out var pid) && pid.ValueKind == JsonValueKind.String ? pid.GetString() : null;
        bool loop = it.TryGetProperty("loop", out var lp) && lp.ValueKind == JsonValueKind.True;
        return new PairInteraction(Json.Str(it, "id"), Json.Str(it, "kind"), Json.Str(it, "role"), Json.Str(it, "partner"),
                                   new PairAnchor(Json.Num(a, "x"), Json.Num(a, "z"), Json.Num(a, "yaw"), place),
                                   Json.NumOrNull(it, "elapsed_s") ?? double.NaN, Json.NumOrNull(it, "clip_duration_s") ?? 0,
                                   loop, Json.NumOrNull(it, "rate") ?? 0);
    }
}

/// <summary>§ A11 <c>travel</c>: the metre polyline and the distance already walked (both null under fog).</summary>
public sealed record TravelInfo(List<(double X, double Z)>? Waypoints, double? ProgressM);

/// <summary>
/// The parts of a world-map LOCATION row the far-view huddle needs (the browser's
/// <c>buildPlace</c>): pin, yaw, footprint width (bounding box of
/// <c>boundary</c>, else <c>plan_width_m</c>, <c>footprintWidth</c>) and whether
/// it is a building (<c>!map3d.area_model</c>, <c>isAreaLocation</c>).
/// </summary>
public sealed record MapPlace(string Id, double X, double Z, double YawDeg, double Width, bool IsBuilding)
{
    /// <summary>Placed rows only — the browser builds a tile only for those (<c>footprintCentre</c>).</summary>
    public static Dictionary<string, MapPlace> ParsePlaced(JsonElement root)
    {
        var map = new Dictionary<string, MapPlace>();
        foreach (var l in Json.Arr(root, "locations"))
        {
            if (l.ValueKind != JsonValueKind.Object) continue;
            var id = Json.Str(l, "id");
            var x = Json.NumOrNull(l, "pos_x");
            var z = Json.NumOrNull(l, "pos_z");
            if (id.Length == 0 || x is null || z is null) continue;
            l.TryGetProperty("map3d", out var m3);
            var ring = l.TryGetProperty("boundary", out var b) && b.ValueKind == JsonValueKind.Array ? Json.Ring(b)
                     : m3.ValueKind == JsonValueKind.Object && m3.TryGetProperty("boundary", out var mb) ? Json.Ring(mb)
                     : Array.Empty<(double X, double Z)>();
            double width = 0;
            if (ring.Length > 0)
                width = Math.Max(ring.Max(p => p.X) - ring.Min(p => p.X), ring.Max(p => p.Z) - ring.Min(p => p.Z));
            else
            {
                var w = Json.NumOrNull(l, "plan_width_m")
                        ?? (m3.ValueKind == JsonValueKind.Object ? Json.NumOrNull(m3, "plan_width_m") : null);
                width = w is > 0 ? w.Value : 0;
            }
            bool area = m3.ValueKind == JsonValueKind.Object && m3.TryGetProperty("area_model", out var am)
                        && am.ValueKind is not (JsonValueKind.Null or JsonValueKind.False or JsonValueKind.Undefined)
                        && !(am.ValueKind == JsonValueKind.String && am.GetString() == "");
            map[id] = new MapPlace(id, x.Value, z.Value, Json.Num(l, "yaw_deg"), width, !area);
        }
        return map;
    }
}

/// <summary>A journey point (<c>travellerState</c>): world x/z and the rule ("journey" / "journey-pos").</summary>
public readonly record struct FigureSpot(double X, double Z, string Rule);

/// <summary>
/// WHERE one character is drawn and HOW it gets there — one entry of the browser's <c>computeNpcPlacements</c> (the
/// avatar's own special cases are E6/E7). <see cref="Pos"/> in world metres; <see cref="Rule"/> = journey, journey-pos,
/// free, tile (the huddle) or the room branch (seat, pool, corridor, pos, centre); <see cref="OnTerrain"/> = a point on
/// the open ground (journey, free) whose height follows the world while the figure moves.
/// </summary>
public sealed record FigurePlan(string Name, Vec3 Pos, string Rule, bool Snap, bool Hidden, Vec3? Face,
                                (double Tilt, double Roll)? Lean, bool OnTerrain, string? InRoom = null)
{
    /// <summary>The actual marker or selected fallback surface; ground without one.</summary>
    public string SurfaceGroup { get; init; } = "ground";
    /// <summary>A real room change was routed this pass (<c>transition === 'route'</c>): a climb left from before ends.</summary>
    public bool Routed { get; init; }
    /// <summary>The stations of that route (doors, landings, lift stops; npcs.ts <c>st.via</c>); null = none.</summary>
    public IReadOnlyList<Vec3>? Via { get; init; }
    /// <summary>The stair legs of that route (the NPC's guided climb, unarmed); empty = no ride.</summary>
    public IReadOnlyList<Scene.StairLeg> Legs { get; init; } = Array.Empty<Scene.StairLeg>();
}

/// <summary>What a location's BUILT tile hands the placement (main.ts <c>residency.get(loc).tile</c> + its lookups).</summary>
public sealed record LocationPlacement(PlacementTile Tile, bool Near, Func<double, double, double> GroundY,
                                       Func<string, double, double, double?> RoomStandY)
{
    /// <summary>The doors, stairs and lift of the mounted scene for a room change (null = no routing: straight line).</summary>
    public RouteTile? Route { get; init; }
}

/// <summary>
/// WHICH characters stand on the map and WHERE — client3d/src/main.ts <c>computeNpcPlacements</c> without the avatar's
/// own branches (suppressed journey, waiting for its place: E6/E7):
///
///   1. <b>journey</b> (<c>travellerState</c>): <c>travel</c> with ≥ 2 <c>waypoints</c> AND a <c>progress_m</c> → the
///      point <c>progress_m</c> metres along the polyline (§ A11, progress clamped to [0, total]); a withheld or
///      degenerate route falls back to <c>pos</c> ("journey-pos"); the figure stands on the world terrain.
///   2. <c>placementOf(hasTile, pos)</c> (vector-checked): <b>free</b> = the point on the terrain (a snap when it was
///      drawn in a room), <b>offmap</b> = not drawn;
///   3. <b>tile</b>: per location, the room ladder <see cref="NpcPlacement.PlaceAtLocation"/> (seat, pool, corridor,
///      server pos, centre; else the huddle on the tile ground), with facing, lean, hidden and snap from it.
///
/// <paramref name="shown"/> is the session's <c>shownPlacement</c> map: a traveller or free figure is reset to
/// {null, false}, a tile figure rewritten whenever its transition is not "stay". Pure, so tests derive it by hand.
/// </summary>
public static class FigurePlacement
{
    public static List<FigurePlan> Plan(IReadOnlyList<CharacterRow> rows, Func<string, LocationPlacement?> tileOf,
                                        Func<double, double, double> terrainY, Dictionary<string, ShownPlacement> shown,
                                        Func<string, Vec3?> targetCentre)
    {
        var plans = new List<FigurePlan>();
        var byLoc = new Dictionary<string, List<CharacterRow>>();
        var order = new List<string>();
        foreach (var c in rows)
        {
            if (Journey(c) is { } j)
            {
                plans.Add(new FigurePlan(c.Name, new Vec3(j.X, terrainY(j.X, j.Z), j.Z), j.Rule, false, false, null, null, true));
                shown[c.Name] = new ShownPlacement(null, false);
                continue;
            }
            var placement = FigureGround.PlacementOf(tileOf(c.LocationId) is not null, c.PosX, c.PosZ);
            if (placement.Kind == PlacementKind.Free && placement.Pos is { } p)
            {
                bool wasInRoom = shown.TryGetValue(c.Name, out var prev) && prev.Room is not null;
                plans.Add(new FigurePlan(c.Name, new Vec3(p.X, terrainY(p.X, p.Z), p.Z), "free", wasInRoom, false, null, null, true));
                shown[c.Name] = new ShownPlacement(null, false);
                continue;
            }
            if (placement.Kind == PlacementKind.Offmap) continue;
            if (!byLoc.TryGetValue(c.LocationId, out var list))
            {
                byLoc[c.LocationId] = list = new List<CharacterRow>();
                order.Add(c.LocationId);
            }
            list.Add(c);
        }
        foreach (var locId in order)
        {
            var loc = tileOf(locId)!;
            var chars = byLoc[locId];
            var roomOf = chars.ToDictionary(c => c.Name, c => c.RoomId);
            var placed = NpcPlacement.PlaceAtLocation(
                chars.Select(c => new PlacementRow(c.Name, c.HasPos ? new P2(c.PosX!.Value, c.PosZ!.Value) : null, c.Place,
                                                   c.ActivityAnimation, c.MovementTargetId)).ToList(),
                loc.Tile,
                new PlacementContext
                {
                    LocId = locId, Near = loc.Near,
                    RoomOf = name => roomOf.TryGetValue(name, out var r) ? r : null,
                    ShownOf = name => shown.TryGetValue(name, out var s) ? s : null,
                    RoomStandY = loc.RoomStandY, GroundY = loc.GroundY, TargetCentre = targetCentre,
                });
            foreach (var f in placed)
            {
                // main.ts: the room the figure was drawn in is read BEFORE the new placement is filed — the start of the walk.
                var prevRoom = shown.TryGetValue(f.Row.Name, out var prev) ? prev.Room : null;
                if (f.Transition != FigureTransition.Stay) shown[f.Row.Name] = new ShownPlacement(f.InRoom, f.InteriorShown);
                NpcRoutePlan? route = f.Transition == FigureTransition.Route && loc.Route is { } rt
                    ? NpcRoute.Plan(rt, prevRoom, f.InRoom) : null;
                plans.Add(new FigurePlan(f.Row.Name, f.Pos, f.Branch == "huddle" ? "tile" : f.Branch,
                                         f.Transition == FigureTransition.Snap, f.Hidden, f.Face, f.Lean, false, f.InRoom)
                {
                    SurfaceGroup = f.SurfaceGroup,
                    Routed = f.Transition == FigureTransition.Route,
                    Via = route is { Via.Count: > 0 } ? route.Via : null,
                    Legs = route?.Legs ?? (IReadOnlyList<Scene.StairLeg>)Array.Empty<Scene.StairLeg>(),
                });
            }
        }
        return plans;
    }

    /// <summary>
    /// <c>travellerState</c>: the point <c>progress_m</c> along ≥ 2 waypoints ("journey"), else — a withheld or
    /// degenerate route — the row's own <c>pos</c> ("journey-pos"); null when the row is not travelling or has no point.
    /// </summary>
    public static FigureSpot? Journey(CharacterRow c)
    {
        if (c.Travel is not { } tr) return null;
        if (tr.Waypoints is { Count: >= 2 } wp && tr.ProgressM is { } prog)
        {
            var (x, z) = PointAtDistance(wp, Math.Clamp(prog, 0, PolylineLength(wp)));
            return new FigureSpot(x, z, "journey");
        }
        return c.HasPos ? new FigureSpot(c.PosX!.Value, c.PosZ!.Value, "journey-pos") : null;
    }

    public static double PolylineLength(IReadOnlyList<(double X, double Z)> wp)
    {
        double total = 0;
        for (int i = 0; i + 1 < wp.Count; i++) total += Dist(wp[i], wp[i + 1]);
        return total;
    }

    /// <summary>§ A11: walk <paramref name="d"/> metres down the polyline; past the end = the last point.</summary>
    public static (double X, double Z) PointAtDistance(IReadOnlyList<(double X, double Z)> wp, double d)
    {
        for (int i = 0; i + 1 < wp.Count; i++)
        {
            double len = Dist(wp[i], wp[i + 1]);
            if (d <= len)
            {
                double t = len > 0 ? d / len : 0;
                return (wp[i].X + (wp[i + 1].X - wp[i].X) * t, wp[i].Z + (wp[i + 1].Z - wp[i].Z) * t);
            }
            d -= len;
        }
        return wp[^1];
    }

    private static double Dist((double X, double Z) a, (double X, double Z) b)
        => Math.Sqrt((b.X - a.X) * (b.X - a.X) + (b.Z - a.Z) * (b.Z - a.Z));
}
